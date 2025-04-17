#!/bin/bash
set -e

HOSTNAME=$1
IS_PRIMARY=$2

hostnamectl set-hostname $HOSTNAME

# Containerd & K8s install
apt-get update && apt-get install -y curl gnupg2 software-properties-common apt-transport-https ca-certificates
apt-get install -y containerd
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml
systemctl restart containerd && systemctl enable containerd

# Kubernetes repo
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-archive-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-archive-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /" | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update && apt-get install -y kubelet kubeadm kubectl && apt-mark hold kubelet kubeadm kubectl

# Networking modules
modprobe overlay && modprobe br_netfilter
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-ip6tables = 1
EOF
sysctl --system

if [ "$IS_PRIMARY" == "true" ]; then
  kubeadm init --apiserver-advertise-address=192.168.56.101 --pod-network-cidr=192.168.0.0/16 --node-name=$HOSTNAME | tee /vagrant/kubeadm_init.log

  mkdir -p /home/vagrant/.kube
  cp /etc/kubernetes/admin.conf /home/vagrant/.kube/config
  chown vagrant:vagrant /home/vagrant/.kube/config

  grep "kubeadm join" /vagrant/kubeadm_init.log -A 2 > /vagrant/kubeadm_join.sh
  sed -i 's/kubeadm join /kubeadm join --node-name=$(hostname) /' /vagrant/kubeadm_join.sh
  chmod +x /vagrant/kubeadm_join.sh

  su - vagrant -c "kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.25.0/manifests/calico.yaml --validate=false"
else
  echo "Waiting for kubeadm_join.sh..."
  while [ ! -f /vagrant/kubeadm_join.sh ]; do sleep 5; done
  bash /vagrant/kubeadm_join.sh --control-plane
fi

