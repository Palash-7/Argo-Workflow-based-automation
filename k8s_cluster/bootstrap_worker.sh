#!/bin/bash
set -e

HOSTNAME=$1
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

echo "Waiting for kubeadm_join.sh..."
while [ ! -f /vagrant/kubeadm_join.sh ]; do sleep 5; done

bash /vagrant/kubeadm_join.sh

