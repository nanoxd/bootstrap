# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure(2) do |config|
  config.vm.box = "yosemite"
  config.ssh.insert_key = false
  config.vm.provider "vmware_fusion" do |vb|
    vb.gui = true
    vb.memory = "4096"
  end
end
