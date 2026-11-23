"""Tests for sim-janitor with simctl, ps and the clock stubbed.

simctl and ps are replaced by small scripts that read a JSON fixture and
record their calls, so the real subprocess path, timeouts included, runs.

    python3 -m unittest discover -s tests
"""
import contextlib
import fcntl
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'sim-janitor'


def load_janitor():
    sys.dont_write_bytecode = True
    loader = SourceFileLoader('sim_janitor', str(SCRIPT))
    spec = importlib.util.spec_from_loader('sim_janitor', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


janitor = load_janitor()

FAKE_XCRUN = '''#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
fixture_path = os.path.join(here, 'fixture.json')
fixture = json.load(open(fixture_path))
args = sys.argv[1:]
assert args[0] == 'simctl', args
args = args[1:]
device_set = 'default'
if args[:2] == ['--set', 'testing']:
    device_set, args = 'testing', args[2:]
with open(os.path.join(here, 'calls.log'), 'a') as log:
    log.write(json.dumps([device_set] + args) + '\\n')
time.sleep(fixture.get('hang', {{}}).get(args[0] + ':' + device_set, 0))
if fixture.get('fail', {{}}).get(args[0] + ':' + device_set):
    sys.stderr.write('simctl failed\\n')
    sys.exit(1)
devices = fixture['sets'][device_set]
if args[0] == 'list':
    print(json.dumps({{'devices': {{'com.apple.CoreSimulator.SimRuntime.iOS-27-2': devices}}}}))
elif args[0] == 'shutdown':
    if fixture.get('probe_leases'):
        # What a `sim-janitor lease` would find while this shutdown runs.
        import fcntl
        results = []
        for udid in fixture.get('probe_udids') or [args[1]]:
            try:
                with open(os.path.join(fixture['probe_leases'], udid + '.lock'), 'rb') as lease:
                    try:
                        fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        results.append([udid, 'free'])
                    except OSError:
                        results.append([udid, 'blocked'])
            except OSError:
                results.append([udid, 'missing'])
        with open(os.path.join(here, 'probes.log'), 'a') as out:
            out.write(json.dumps(results) + '\\n')
    time.sleep(fixture.get('hang_device', {{}}).get(args[1], 0))
    for device in devices:
        if device['udid'] == args[1]:
            device['state'] = 'Shutdown'
    json.dump(fixture, open(fixture_path, 'w'))
    if fixture.get('touch_on_shutdown'):
        open(fixture['touch_on_shutdown'], 'a').close()
'''

FAKE_PS = '''#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
fixture = json.load(open(os.path.join(here, 'fixture.json')))
counter = os.path.join(here, 'ps.count')
count = int(open(counter).read()) if os.path.exists(counter) else 0
open(counter, 'w').write(str(count + 1))
if fixture.get('ps_fail'):
    sys.exit(1)
tables = fixture['ps']
table = tables[min(count, len(tables) - 1)]
if table == 'fail':
    sys.exit(1)
for row in table:
    pid, ppid, start, command = row[:4]
    stat = row[4] if len(row) > 4 else 'Ss'
    print('%6d %6d %-4s %s %s' % (pid, ppid, stat, start, command))
'''

T0 = 1795400000.0
DEVICE = '241E5D48-2E1F-4C96-B2F5-01C007E29842'
OTHER = '0191A3D9-5CC4-4E92-AA94-92DA2C59BA5C'
CLONE = 'C85C6A82-E0CB-45BE-92D3-ED82C22C55E7'
HOST = '/Users/test/Library/Developer'


def lstart(epoch):
    return time.strftime('%a %b %d %H:%M:%S %Y', time.localtime(epoch))


def launchd_sim(pid, udid, booted, testing=False):
    where = 'XCTestDevices' if testing else 'CoreSimulator/Devices'
    return [pid, 1, lstart(booted), f'launchd_sim {HOST}/{where}/{udid}/data/var/run/launchd_bootstrap.plist']


def device(udid, name='iPhone gate 0', state='Booted'):
    return dict(udid=udid, name=name, state=state)


BASE_PS = [[1, 0, lstart(T0 - 86400), '/sbin/launchd']]


class JanitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sim-janitor-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        for name, source in (('xcrun', FAKE_XCRUN), ('ps', FAKE_PS)):
            path = self.bin / name
            path.write_text(source.format(python=sys.executable))
            path.chmod(0o755)
        self.home = self.tmp / 'home'
        self.claims = self.home / '.agent-device/device-claims'
        self.now = T0
        self.config = janitor.Config(home=self.home)
        self.config.state_dir = self.home / 'state'
        self.config.lease_dir = self.config.state_dir / 'leases'
        self.config.state_file = self.config.state_dir / 'state.json'
        self.config.lock_file = self.config.state_dir / 'janitor.lock'
        self.config.log_file = self.home / 'sim-janitor.log'
        self.config.pause_file = self.home / '.agents/sim-janitor.pause'
        self.config.claim_dirs = [self.claims]
        self.config.xcrun = str(self.bin / 'xcrun')
        self.config.ps = str(self.bin / 'ps')
        self.config.list_timeout = 5
        self.config.ps_timeout = 5
        self.config.shutdown_timeout = 5
        self.config.grace = 30 * 60
        self.config.clock = lambda: self.now
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]])

    # --- helpers -------------------------------------------------------------

    def fixture(self, default=(), testing=(), ps=None, **extra):
        data = dict(sets=dict(default=list(default), testing=list(testing)), ps=ps or [BASE_PS], **extra)
        (self.bin / 'fixture.json').write_text(json.dumps(data))
        (self.bin / 'ps.count').unlink() if (self.bin / 'ps.count').exists() else None

    def calls(self):
        try:
            lines = (self.bin / 'calls.log').read_text().splitlines()
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in lines]

    def shutdowns(self):
        return [call for call in self.calls() if call[1] == 'shutdown']

    def log_text(self):
        try:
            return self.config.log_file.read_text()
        except FileNotFoundError:
            return ''

    def run_pass(self, dry_run=False):
        return janitor.command_run(self.config, dry_run)

    def seed(self, key, since):
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.state_file.write_text(json.dumps({'since': {key: since}}))

    def status(self):
        out = io.StringIO()
        janitor.command_status(self.config, out=out)
        return out.getvalue()

    def claim(self, udid, pid, start, session='t3-session', **extra):
        self.claims.mkdir(parents=True, exist_ok=True)
        record = dict(schemaVersion=3, deviceKey=f'local:apple:ios:{udid}', session=session,
                      device=dict(id=udid, family='apple', kind='simulator'), ownerPid=pid,
                      ownerStartTime=start, claimOwnerKind='open-session', **extra)
        (self.claims / f'{session.replace(":", "_")}.json').write_text(json.dumps(record))

    # --- grace ---------------------------------------------------------------

    def test_grace_expiry(self):
        self.assertEqual(self.run_pass(), 0)
        self.assertEqual(self.shutdowns(), [], 'a device first seen now is idle from now')
        self.now = T0 + 29 * 60
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.now = T0 + 31 * 60
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])
        self.assertIn(f'shut down iPhone gate 0 ({DEVICE}, default set) after 31m idle', self.log_text())
        self.assertNotIn(f'default:{DEVICE}', json.loads(self.config.state_file.read_text())['since'])

    def test_grace_override(self):
        self.config.grace = 5 * 60
        self.run_pass()
        self.now = T0 + 6 * 60
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_grace_from_environment_and_flag(self):
        os.environ['SIM_JANITOR_GRACE_MINUTES'] = '12'
        self.addCleanup(os.environ.pop, 'SIM_JANITOR_GRACE_MINUTES')
        self.assertEqual(janitor.Config(home=self.home).grace, 12 * 60)
        self.config.state_dir.mkdir(parents=True)
        self.config.pause_file.parent.mkdir(parents=True)
        self.config.pause_file.touch()
        janitor.main(['run', '--grace-minutes', '7'], config=self.config)
        self.assertEqual(self.config.grace, 7 * 60)

    def test_reboot_restarts_the_idle_clock(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 60)]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [], 'booted a minute ago, so idle for a minute')

    def test_never_touches_a_device_that_is_not_booted(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE, state='Shutdown'), device(OTHER, 'x', state='Shutting Down')])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    # --- owners --------------------------------------------------------------

    def test_lease_protects_device(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.lease_dir.mkdir(parents=True)
        with open(self.config.lease_dir / f'{DEVICE}.lock', 'a') as lease:
            fcntl.flock(lease, fcntl.LOCK_SH)
            self.run_pass()
            self.assertIn('owner: lease', self.status())
        self.assertEqual(self.shutdowns(), [])
        self.assertEqual(json.loads(self.config.state_file.read_text())['since'][f'default:{DEVICE}'], T0)

    def test_released_lease_does_not_protect(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.lease_dir.mkdir(parents=True)
        (self.config.lease_dir / f'{DEVICE}.lock').touch()
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_lease_command_holds_the_lock_while_the_command_runs(self):
        probe = textwrap.dedent(f'''
            import fcntl, sys
            with open({str(self.config.lease_dir / (DEVICE + ".lock"))!r}, "rb") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    print("free")
                except OSError:
                    print("held")
            sys.exit(7)
        ''')
        env = dict(os.environ, SIM_JANITOR_STATE_DIR=str(self.config.state_dir))
        result = subprocess.run([sys.executable, str(SCRIPT), 'lease', DEVICE.lower(), '--', sys.executable, '-c', probe],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.stdout.strip(), 'held')
        self.assertEqual(result.returncode, 7, 'the command\'s exit status passes through')
        self.assertFalse(janitor.lease_held(self.config, DEVICE), 'released once the command exits')

    def test_lease_rejects_bad_udid(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(janitor.main(['lease', 'not-a-udid', '--', 'true'], config=self.config), 64)
            self.assertEqual(janitor.main(['lease', DEVICE, 'true'], config=self.config), 64)

    def test_argv_owner_protects_device(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        xcodebuild = [500, 400, lstart(T0 - 60), f'/usr/bin/xcodebuild test -scheme App -destination id={DEVICE}']
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), xcodebuild]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.assertIn('owner: process 500: /usr/bin/xcodebuild', self.status())
        self.assertEqual(json.loads(self.config.state_file.read_text())['since'][f'default:{DEVICE}'], T0)

    def test_lowercase_udid_in_argv_counts(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        maestro = [501, 400, lstart(T0), f'maestro --device {DEVICE.lower()} test flow.yaml']
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [maestro]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_simulator_runtime_tree_is_not_an_owner(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        inside = [
            launchd_sim(100, DEVICE, T0 - 7200),
            [101, 100, lstart(T0 - 7000), f'/usr/libexec/diagnosticd --device {DEVICE}'],
            [102, 101, lstart(T0 - 7000), f'{HOST}/CoreSimulator/Devices/{DEVICE}/data/Containers/App.app/App'],
            [103, 400, lstart(T0 - 10), f'tail -f {HOST}/CoreSimulator/Devices/{DEVICE}/data/log.txt'],
        ]
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + inside])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_owner_arriving_before_shutdown_keeps_device(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        quiet = BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]
        busy = quiet + [[600, 400, lstart(T0), f'xcrun simctl launch {DEVICE} com.example.app']]
        self.fixture(default=[device(DEVICE)], ps=[quiet, busy])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.assertIn('an owner arrived', self.log_text())

    # --- agent-device --------------------------------------------------------

    def runner(self, pid=700, ppid=1):
        return [pid, ppid, lstart(T0 - 3600),
                '/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild test-without-building '
                '-only-testing AgentDeviceRunnerUITests/RunnerTests/testCommand -xctestrun '
                f'/Users/test/.agent-device/apple-runner/derived/AgentDeviceRunner.env.session-{DEVICE}-owner-1.xctestrun']

    def test_abandoned_agent_device_runner_does_not_protect(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.claim(DEVICE, 4242, lstart(T0 - 9000))
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), self.runner()]])
        status = self.status()
        self.assertIn('not an owner: agent-device runner 700', status)
        self.assertIn('daemon 4242 is gone', status)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_live_agent_device_session_protects(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        daemon = [4242, 1, lstart(T0 - 9000), '/opt/homebrew/bin/node /x/agent-device/dist/src/internal/daemon.js']
        self.claim(DEVICE, 4242, lstart(T0 - 9000))
        self.fixture(default=[device(DEVICE)],
                     ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), daemon, self.runner(ppid=4242)]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.assertIn('owner: agent-device session t3-session (daemon 4242)', self.status())
        self.assertNotIn('owners: none found', self.status())

    def test_reused_daemon_pid_does_not_protect(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        stranger = [4242, 1, lstart(T0 - 60), '/usr/bin/some-other-thing']
        self.claim(DEVICE, 4242, lstart(T0 - 9000))
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), stranger]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_half_written_claim_protects_only_while_fresh(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.claims.mkdir(parents=True)
        path = self.claims / 'partial.json'
        path.write_text('{"device": {"id": "%s"' % DEVICE)
        os.utime(path, (T0 - 10, T0 - 10))
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.now = T0 + 31 * 60
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    # --- the testing set -----------------------------------------------------

    def test_testing_set_clone_is_shut_down_there(self):
        self.seed(f'testing:{CLONE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE, 'Gate', state='Shutdown')],
                     testing=[device(CLONE, 'Clone 1 of Gate')],
                     ps=[BASE_PS + [launchd_sim(100, CLONE, T0 - 7200, testing=True)]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['testing', 'shutdown', CLONE]])

    def test_clone_is_owned_through_its_source(self):
        self.seed(f'testing:{CLONE}', T0 - 3 * 3600)
        xcodebuild = [500, 400, lstart(T0 - 60), f'xcodebuild test -parallel-testing-enabled YES -destination id={DEVICE}']
        self.fixture(default=[device(DEVICE, 'Gate', state='Shutdown')],
                     testing=[device(CLONE, 'Clone 1 of Gate')],
                     ps=[BASE_PS + [launchd_sim(100, CLONE, T0 - 7200, testing=True), xcodebuild]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.assertIn(f'(via source {DEVICE})', self.status())

    # --- robustness ----------------------------------------------------------

    def test_kill_switch(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.pause_file.parent.mkdir(parents=True)
        self.config.pause_file.touch()
        self.assertEqual(self.run_pass(), 0)
        self.assertEqual(self.calls(), [])
        self.assertIn('paused', self.log_text())

    def test_simctl_list_timeout_does_not_wedge_the_pass(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.list_timeout = 1
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]],
                     hang={'list:testing': 30})
        started = time.monotonic()
        self.run_pass()
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn('timed out after 1s', self.log_text())
        self.assertIn('testing set unlisted', self.log_text())
        self.assertIn(['default', 'shutdown', DEVICE], self.shutdowns(), 'the default set is still served')

    def test_simctl_default_list_timeout_ends_the_pass(self):
        self.config.list_timeout = 1
        self.fixture(default=[device(DEVICE)], hang={'list:default': 30})
        started = time.monotonic()
        self.assertEqual(self.run_pass(), 1)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn('nothing judged', self.log_text())

    def test_simctl_shutdown_timeout_does_not_wedge_the_pass(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.shutdown_timeout = 1
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]],
                     hang={'shutdown:default': 30})
        started = time.monotonic()
        self.assertEqual(self.run_pass(), 1)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn('could not shut down', self.log_text())
        self.assertIn('pass done', self.log_text())

    def test_unreadable_process_table_keeps_everything(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE)], ps_fail=True)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.assertIn('keeping every device', self.log_text())

    def test_single_instance_lock(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        with open(self.config.lock_file, 'a') as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_pass(), 0)
        self.assertEqual(self.calls(), [])
        self.assertIn('another pass is running', self.log_text())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]], 'runs once the lock is free')

    def test_dry_run_does_nothing(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        before = self.config.state_file.read_text()
        self.assertEqual(self.run_pass(dry_run=True), 0)
        self.assertEqual(self.shutdowns(), [])
        self.assertEqual(self.config.state_file.read_text(), before)
        self.assertIn('[dry-run] would shut down iPhone gate 0', self.log_text())

    def test_every_pass_logs_a_line(self):
        self.fixture(default=[])
        self.run_pass()
        self.assertIn('pass done: 0 booted', self.log_text())

    def test_status_reports_without_side_effects(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        before = self.config.state_file.read_text()
        out = self.status()
        self.assertIn(f'iPhone gate 0 ({DEVICE}, default set)', out)
        self.assertIn('idle 2h00m -> shut down', out)
        self.assertEqual(self.shutdowns(), [])
        self.assertEqual(self.config.state_file.read_text(), before)
        self.assertEqual(self.log_text(), '')

    def test_log_rotates(self):
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.log_file.write_text('x' * (janitor.LOG_LIMIT + 1))
        janitor.log(self.config, 'hello')
        self.assertTrue(self.config.log_file.with_name('sim-janitor.log.1').exists())
        self.assertIn('hello', self.log_text())

    # --- A: each shutdown is judged afresh ----------------------------------

    def two_idle_devices(self, *extra_tables):
        """DEVICE, idle longer, goes before OTHER. `extra_tables` are what
        ps shows at each final check, in order."""
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.state_file.write_text(json.dumps({'since': {
            f'default:{DEVICE}': T0 - 5 * 3600, f'default:{OTHER}': T0 - 5 * 3600}}))
        quiet = BASE_PS + [launchd_sim(100, DEVICE, T0 - 4 * 3600), launchd_sim(200, OTHER, T0 - 3 * 3600)]
        return quiet, dict(default=[device(DEVICE), device(OTHER, 'iPhone gate 1')], ps=[quiet, quiet, *extra_tables] if extra_tables else [quiet])

    def test_device_whose_launchd_sim_exits_during_the_final_check_is_left_alone(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        busy = BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]
        self.fixture(default=[device(DEVICE)], ps=[busy, BASE_PS])
        self.assertEqual(self.run_pass(), 0)
        self.assertEqual(self.shutdowns(), [], 'something else already shut it down')
        self.assertIn(f'left iPhone gate 0 ({DEVICE}, default set) alone: its launchd_sim exited', self.log_text())

    def test_a_final_check_that_cannot_finish_goes_behind_the_others(self):
        quiet, fixture = self.two_idle_devices()
        fixture['ps'] = [quiet, 'fail', quiet]
        self.fixture(**fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', OTHER]])
        self.assertIn(f'kept iPhone gate 0 ({DEVICE}, default set) this pass: process table unreadable',
                      self.log_text())
        state = json.loads(self.config.state_file.read_text())
        self.assertEqual(state['unchecked'], {f'default:{DEVICE}': T0})

    def test_unchecked_devices_rotate_behind_devices_that_were_checked(self):
        quiet, fixture = self.two_idle_devices()
        state = json.loads(self.config.state_file.read_text())
        state['unchecked'] = {f'default:{DEVICE}': T0 - 300}
        self.config.state_file.write_text(json.dumps(state))
        self.fixture(**fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', OTHER], ['default', 'shutdown', DEVICE]],
                         'the device whose last check could not finish waits behind the other')
        self.assertEqual(json.loads(self.config.state_file.read_text())['unchecked'], {})

    def test_each_final_listing_gets_only_the_time_left(self):
        self.config.list_timeout = 30
        janitor_calls = []
        real = janitor.list_devices

        def spy(config, device_set, timeout=None):
            janitor_calls.append(timeout)
            return real(config, device_set, timeout)

        janitor.list_devices = spy
        self.addCleanup(setattr, janitor, 'list_devices', real)
        deadline = time.monotonic() + 4
        janitor.inventory(self.config, ('default', 'testing'), deadline=deadline)
        self.assertEqual(len(janitor_calls), 2)
        self.assertTrue(all(t <= 4 for t in janitor_calls), janitor_calls)
        self.assertGreaterEqual(janitor_calls[0], janitor_calls[1])

    def test_owner_arriving_during_an_earlier_shutdown_keeps_the_next_device(self):
        quiet, fixture = self.two_idle_devices()
        test_run = [800, 400, lstart(T0), f'/usr/bin/xcodebuild test -destination id={OTHER}']
        fixture['ps'] = [quiet, quiet, quiet + [test_run]]
        self.fixture(**fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])
        self.assertIn(f'kept iPhone gate 1 ({OTHER}, default set): an owner arrived (process 800', self.log_text())

    def test_reboot_during_an_earlier_shutdown_resets_the_next_devices_idle_time(self):
        quiet, fixture = self.two_idle_devices()
        rebooted = BASE_PS + [launchd_sim(100, DEVICE, T0 - 4 * 3600), launchd_sim(201, OTHER, T0 - 30)]
        fixture['ps'] = [quiet, quiet, rebooted]
        self.fixture(**fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])
        self.assertIn(f'kept iPhone gate 1 ({OTHER}, default set): idle only 30s now', self.log_text())

    def test_each_device_gets_its_own_final_look(self):
        quiet, fixture = self.two_idle_devices()
        self.fixture(**fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE], ['default', 'shutdown', OTHER]])
        lists = [call for call in self.calls() if call[1] == 'list']
        self.assertEqual(len(lists), 4, 'one pass listing of both sets, then the default set before each shutdown')
        self.assertEqual(int((self.bin / 'ps.count').read_text()), 3, 'one ps for the pass, one per device')

    # --- B: the lease file is locked through the shutdown -------------------

    def probes(self):
        try:
            return [json.loads(line) for line in (self.bin / 'probes.log').read_text().splitlines()]
        except FileNotFoundError:
            return []

    def test_lease_is_locked_while_simctl_shutdown_runs(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]],
                     probe_leases=str(self.config.lease_dir))
        self.run_pass()
        self.assertEqual(self.probes(), [[[DEVICE, 'blocked']]], 'a lease started now waits for the janitor')
        self.assertFalse(janitor.lease_held(self.config, DEVICE), 'released once the shutdown returns')
        outcome = json.loads(janitor.lease_path(self.config, DEVICE).read_text())
        self.assertEqual(outcome['result'], 'shut down')

    def test_clone_shutdown_locks_the_source_lease_too(self):
        self.seed(f'testing:{CLONE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE, 'Gate', state='Shutdown')],
                     testing=[device(CLONE, 'Clone 1 of Gate')],
                     ps=[BASE_PS + [launchd_sim(100, CLONE, T0 - 7200, testing=True)]],
                     probe_leases=str(self.config.lease_dir), probe_udids=[CLONE, DEVICE])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['testing', 'shutdown', CLONE]])
        self.assertEqual(self.probes(), [[[CLONE, 'blocked'], [DEVICE, 'blocked']]])

    def test_lease_taken_before_the_lock_keeps_the_device(self):
        self.config.lease_dir.mkdir(parents=True)
        with open(janitor.lease_path(self.config, DEVICE), 'a') as lease:
            fcntl.flock(lease, fcntl.LOCK_SH)
            handles, busy = janitor.lock_leases(self.config, [OTHER, DEVICE])
        self.assertIsNone(handles)
        self.assertEqual(busy, DEVICE)
        self.assertFalse(janitor.lease_held(self.config, OTHER), 'locks already taken are released')

    def test_lease_waits_for_the_janitor_and_says_it_shut_the_device_down(self):
        self.config.lease_dir.mkdir(parents=True)
        path = janitor.lease_path(self.config, DEVICE)
        env = dict(os.environ, SIM_JANITOR_STATE_DIR=str(self.config.state_dir))
        with open(path, 'a+') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            wrapper = subprocess.Popen([sys.executable, str(SCRIPT), 'lease', DEVICE, '--',
                                        sys.executable, '-c', 'print("ran")'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            time.sleep(1)
            self.assertIsNone(wrapper.poll(), 'the lease blocks rather than failing')
            held.truncate(0)
            held.write(json.dumps(dict(result='shut down', at=time.time(), pid=1)) + '\n')
            held.flush()
        out, err = wrapper.communicate(timeout=30)
        self.assertEqual(wrapper.returncode, 0)
        self.assertEqual(out.strip(), 'ran', 'the command still runs')
        self.assertIn('waiting for sim-janitor', err)
        self.assertIn(f'sim-janitor shut {DEVICE} down while this lease waited', err)

    def test_lease_that_did_not_wait_says_nothing(self):
        self.config.lease_dir.mkdir(parents=True)
        janitor.lease_path(self.config, DEVICE).write_text(
            json.dumps(dict(result='shut down', at=time.time(), pid=1)) + '\n')
        env = dict(os.environ, SIM_JANITOR_STATE_DIR=str(self.config.state_dir))
        result = subprocess.run([sys.executable, str(SCRIPT), 'lease', DEVICE, '--', 'true'],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')

    # --- C: budget and retry order ------------------------------------------

    def test_shutdown_timeout_is_capped_at_the_pass_budget(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.pass_budget = 3
        self.config.shutdown_timeout = 60
        self.config.min_step = 0.5
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]],
                     hang={'shutdown:default': 30})
        started = time.monotonic()
        self.assertEqual(self.run_pass(), 1)
        self.assertLess(time.monotonic() - started, 10)
        self.assertRegex(self.log_text(), r'could not shut down .* timed out after [23]s')

    def test_a_device_that_times_out_does_not_starve_the_next(self):
        quiet, fixture = self.two_idle_devices()
        self.fixture(hang_device={DEVICE: 30}, **fixture)
        self.config.pass_budget = 3
        self.config.shutdown_timeout = 2.5
        self.config.min_step = 1
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])
        self.assertIn('pass budget spent, 1 device(s) wait for the next pass', self.log_text())
        attempts = json.loads(self.config.state_file.read_text())['attempts']
        self.assertEqual(attempts[f'default:{DEVICE}']['failures'], 1)
        self.now = T0 + 300
        self.fixture(hang_device={DEVICE: 30}, **fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns()[1], ['default', 'shutdown', OTHER],
                         'the device that never failed goes first')

    def test_repeated_shutdown_failures_back_off(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.config.shutdown_timeout = 1
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]],
                     hang_device={DEVICE: 30})
        self.run_pass()
        self.now = T0 + 300
        self.run_pass()
        self.assertEqual(len(self.shutdowns()), 2)
        self.now = T0 + 600
        self.run_pass()
        self.assertEqual(len(self.shutdowns()), 2, 'two failures in a row wait 10 minutes')
        self.assertIn('failed to shut down 2 times in a row, next try in 5m', self.log_text())
        self.assertIn('2 failed shutdown(s) in a row, next try in 5m', self.status())
        self.now = T0 + 300 + 601
        self.run_pass()
        self.assertEqual(len(self.shutdowns()), 3)
        self.assertEqual(janitor.backoff_left(dict(last=0, failures=9), 0), janitor.BACKOFF_MAX)

    def test_success_clears_the_failure_count(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        state = json.loads(self.config.state_file.read_text())
        state['attempts'] = {f'default:{DEVICE}': dict(last=T0 - 3600, failures=3)}
        self.config.state_file.write_text(json.dumps(state))
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])
        self.assertEqual(json.loads(self.config.state_file.read_text())['attempts'], {})

    # --- D: the pause switch between shutdowns ------------------------------

    def test_pause_appearing_mid_pass_stops_before_the_next_shutdown(self):
        quiet, fixture = self.two_idle_devices()
        self.config.pause_file.parent.mkdir(parents=True)
        self.fixture(touch_on_shutdown=str(self.config.pause_file), **fixture)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])
        self.assertIn(f'paused: {self.config.pause_file} appeared, 1 device(s) left booted', self.log_text())
        self.assertIn('stopped: paused', self.log_text())

    # --- E: agent-device session activity -----------------------------------

    def live_session(self, updated, events=None, session='t3-session', **extra):
        """A claim whose daemon runs, with its events file touched at `events`."""
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        state_dir = self.home / 'agent-device-state'
        daemon = [4242, 1, lstart(T0 - 9000), '/opt/homebrew/bin/node /x/agent-device/dist/src/internal/daemon.js']
        self.claim(DEVICE, 4242, lstart(T0 - 9000), session=session, stateDir=str(state_dir),
                   updatedAtMs=int(updated * 1000), **extra)
        if events is not None:
            folder = state_dir / 'sessions' / janitor.session_dir_name(session)
            folder.mkdir(parents=True)
            (folder / 'events.ndjson').write_text('{}\n')
            os.utime(folder / 'events.ndjson', (events, events))
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), daemon]])

    def test_session_quiet_past_the_cap_does_not_own_the_device(self):
        self.live_session(updated=T0 - 3 * 3600, events=T0 - 2.5 * 3600)
        status = self.status()
        self.assertIn('not an owner: agent-device session t3-session (daemon 4242): '
                      'last activity 2h30m ago, past the 2h00m session cap', status)
        self.assertIn('owners: none found', status)
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_recent_session_events_keep_the_device(self):
        self.live_session(updated=T0 - 3 * 3600, events=T0 - 300, session='t3:odd name')
        self.assertIn('owner: agent-device session t3:odd name (daemon 4242), last activity 5m ago', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_recent_claim_update_keeps_the_device(self):
        self.live_session(updated=T0 - 60, events=T0 - 3 * 3600)
        self.assertIn('last activity 1m ago', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_unreadable_session_activity_counts_as_in_use(self):
        self.live_session(updated=T0 - 3 * 3600, events=None)
        self.assertIn('last activity unknown', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_abandoned_claim_does_not_own_the_device(self):
        self.live_session(updated=T0 - 60, events=T0 - 60, abandonedAtMs=int((T0 - 60) * 1000))
        self.assertIn('not an owner: agent-device session t3-session: closed 1m ago (claim abandoned)', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_transient_command_claim_owns_while_its_daemon_runs(self):
        self.live_session(updated=T0 - 3 * 3600, session='transient:install',
                          **{'transientCommand': 'install'})
        record = json.loads((self.claims / 'transient_install.json').read_text())
        record['claimOwnerKind'] = 'transient-command'
        (self.claims / 'transient_install.json').write_text(json.dumps(record))
        self.assertIn('running one command', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_session_cap_from_environment_and_flag(self):
        os.environ['SIM_JANITOR_SESSION_IDLE_MINUTES'] = '45'
        self.addCleanup(os.environ.pop, 'SIM_JANITOR_SESSION_IDLE_MINUTES')
        self.assertEqual(janitor.Config(home=self.home).session_cap, 45 * 60)
        self.live_session(updated=T0 - 3 * 3600, events=T0 - 3600)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            janitor.main(['status', '--session-idle-minutes', '30'], config=self.config)
        self.assertEqual(self.config.session_cap, 30 * 60)
        self.assertIn('past the 30m session cap', out.getvalue())

    # --- F: devices a test names some other way -----------------------------

    def app(self, pid, started, path='Containers/Bundle/Application', parent=100, stat='Ss'):
        bundle = f'{HOST}/CoreSimulator/Devices/{DEVICE}/data/{path}/6F1D2C3B-4A5E-4F60-8A7B-9C0D1E2F3A4B'
        return [pid, parent, lstart(started), f'{bundle}/Some App.app/SomeApp -AppleLanguages (en)', stat]

    def test_recent_app_start_in_the_device_tree_keeps_it(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE)],
                     ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), self.app(110, T0 - 10 * 60)]])
        self.assertIn('last app or test start: 10m ago, process 110', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200)]])
        self.now = T0 + 15 * 60
        self.run_pass()
        self.assertEqual(self.shutdowns(), [], 'idle from the app start, even after the app exits')
        self.now = T0 + 21 * 60
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_long_running_app_does_not_pin_the_device(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE)],
                     ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), self.app(110, T0 - 7000)]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_extensions_and_system_daemons_are_not_activity(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        widget = [111, 100, lstart(T0 - 60), f'{HOST}/CoreSimulator/Devices/{DEVICE}/data/Containers/Bundle/'
                  'Application/6F1D2C3B-4A5E-4F60-8A7B-9C0D1E2F3A4B/App.app/PlugIns/Widgets.appex/Widgets']
        daemon = [112, 100, lstart(T0 - 60), '/Library/Developer/CoreSimulator/Volumes/iOS/usr/libexec/diagnosticd']
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), widget, daemon]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_test_runner_and_xctest_starts_are_activity(self):
        for command in (f'{HOST}/CoreSimulator/Devices/{DEVICE}/data/Containers/Bundle/Application/'
                        '6F1D2C3B-4A5E-4F60-8A7B-9C0D1E2F3A4B/AppUITests-Runner.app/AppUITests-Runner',
                        '/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneSimulator.platform/'
                        'Developer/Library/Xcode/Agents/xctest'):
            self.assertTrue(janitor.is_app_or_test(command), command)

    def test_destination_by_name_owns_every_booted_device_with_that_name(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        xcodebuild = [500, 400, lstart(T0 - 60), '/usr/bin/xcodebuild test -scheme App '
                      '-destination platform=iOS Simulator,name=iPhone gate 0,OS=latest -quiet']
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), xcodebuild]])
        self.assertIn("owner: process 500 names it 'iPhone gate 0' in -destination", self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_destination_with_another_name_does_not_own(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        xcodebuild = [500, 400, lstart(T0 - 60),
                      "/bin/zsh -c xcodebuild test -destination 'platform=iOS Simulator,name=iPhone gate 01' | xcbeautify"]
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), xcodebuild]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])

    def test_destination_names_parsing(self):
        names = janitor.destination_names
        self.assertEqual(names('xcodebuild -destination platform=iOS Simulator,name=iPhone 17 Pro,OS=27.2 -scheme A'),
                         ['iPhone 17 Pro'])
        self.assertEqual(names("sh -c xcodebuild -destination 'platform=iOS Simulator,name=iPhone 17' | xcbeautify"),
                         ['iPhone 17'])
        self.assertEqual(names('xcodebuild -destination id=' + DEVICE), [])
        self.assertEqual(names('maestro test flow.yaml'), [])

    def test_clone_is_owned_through_its_source_name(self):
        self.seed(f'testing:{CLONE}', T0 - 3 * 3600)
        xcodebuild = [500, 400, lstart(T0 - 60), 'xcodebuild test -destination platform=iOS Simulator,name=Gate']
        self.fixture(default=[device(DEVICE, 'Gate', state='Shutdown')],
                     testing=[device(CLONE, 'Clone 1 of Gate')],
                     ps=[BASE_PS + [launchd_sim(100, CLONE, T0 - 7200, testing=True), xcodebuild]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_debugger_attached_in_the_device_tree_owns_it(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        self.fixture(default=[device(DEVICE)],
                     ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), self.app(110, T0 - 7000, stat='SXs')]])
        self.assertIn('owner: process 110 is being debugged', self.status())
        self.run_pass()
        self.assertEqual(self.shutdowns(), [])

    def test_traced_process_outside_the_device_tree_does_not_own_it(self):
        self.seed(f'default:{DEVICE}', T0 - 3 * 3600)
        other = [300, 1, lstart(T0 - 60), '/usr/bin/some-tool', 'SX']
        self.fixture(default=[device(DEVICE)], ps=[BASE_PS + [launchd_sim(100, DEVICE, T0 - 7200), other]])
        self.run_pass()
        self.assertEqual(self.shutdowns(), [['default', 'shutdown', DEVICE]])


if __name__ == '__main__':
    unittest.main()
