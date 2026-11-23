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
    for device in devices:
        if device['udid'] == args[1]:
            device['state'] = 'Shutdown'
    json.dump(fixture, open(fixture_path, 'w'))
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
for pid, ppid, start, command in tables[min(count, len(tables) - 1)]:
    print('%6d %6d %s %s' % (pid, ppid, start, command))
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

    def claim(self, udid, pid, start, session='t3-session'):
        self.claims.mkdir(parents=True, exist_ok=True)
        record = dict(schemaVersion=3, deviceKey=f'local:apple:ios:{udid}', session=session,
                      device=dict(id=udid, family='apple', kind='simulator'), ownerPid=pid,
                      ownerStartTime=start, claimOwnerKind='open-session')
        (self.claims / f'{session}.json').write_text(json.dumps(record))

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


if __name__ == '__main__':
    unittest.main()
