Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/focal64"
  config.vm.synced_folder ".", "/vagrant", type: "virtualbox"

  # Define your nodes here
  node_names = [
    "master-m001",
    "master-m002",
    "master-m003",
    "worker-w001",
    "worker-w002",
    "worker-w003",
    "worker-w004",
    "worker-w005",
    "worker-w006"
  ]

  ip_base = "192.168.56."
  start_ip = 101
  master_count = 0

  node_names.each_with_index do |name, i|
    config.vm.define name do |node|
      node.vm.hostname = name
      node.vm.network "private_network", ip: "#{ip_base}#{start_ip + i}"

      node.vm.provider "virtualbox" do |vb|
        vb.memory = 2048
        vb.cpus = 2
      end

      if name.include?("master")
        is_first_master = master_count == 0
        node.vm.provision "shell", path: "bootstrap_master.sh", args: [name, is_first_master ? "true" : "false"]
        master_count += 1
      else
        node.vm.provision "shell", path: "bootstrap_worker.sh", args: [name]
      end
    end
  end
end

