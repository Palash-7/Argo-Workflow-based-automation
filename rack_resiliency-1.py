import random
import time
import logging
import paramiko
import libvirt
import os
from kubernetes import client, config

# ========== CONFIG ==========
SSH_USER = "ubuntu"
SSH_KEY_PATH = os.path.expanduser("~/.vagrant.d/insecure_private_key")

NODE_VM_MAP = {
    # Zone A
    "master-m001": {"ip": "192.168.1.101", "vm_name": "master-m001", "zone": "R1"},
    "worker-w001": {"ip": "192.168.1.102", "vm_name": "worker-w001", "zone": "R1"},
    "worker-w002": {"ip": "192.168.1.103", "vm_name": "worker-w002", "zone": "R1"},

    # Zone B
    "master-m002": {"ip": "192.168.1.104", "vm_name": "master-m002", "zone": "R2"},
    "worker-w003": {"ip": "192.168.1.105", "vm_name": "worker-w003", "zone": "R2"},
    "worker-w004": {"ip": "192.168.1.106", "vm_name": "worker-w004", "zone": "R2"},

    # Zone C
    "master-m003": {"ip": "192.168.1.107", "vm_name": "master-m003", "zone": "R3"},
    "worker-w005": {"ip": "192.168.1.108", "vm_name": "worker-w005", "zone": "R3"},
    "worker-w006": {"ip": "192.168.1.109", "vm_name": "worker-w006", "zone": "R3"},
}

CRITICAL_SERVICES = [
    "etcd", "postgres", "auth-service", "billing-service",
    "user-service", "search-service", "inventory-service"
]

logging.basicConfig(filename="rack_resilience.log", level=logging.INFO)

# ========== K8S CLIENT SETUP ==========
config.load_kube_config()
v1 = client.CoreV1Api()

# ========== HEALTH CHECKS ==========
def check_node_health():
    nodes = v1.list_node().items
    for node in nodes:
        node_name = node.metadata.name
        for condition in node.status.conditions:
            if condition.type == "Ready" and condition.status != "True":
                logging.warning(f"Node {node_name} is not Ready")

def check_service_health():
    for svc in CRITICAL_SERVICES:
        pods = v1.list_pod_for_all_namespaces(label_selector=f'app={svc}').items
        if not pods:
            logging.warning(f"No pods found for {svc}")
            continue
        zone_dist = {}
        for pod in pods:
            zone = pod.metadata.labels.get("topology.kubernetes.io/zone", "unknown")
            zone_dist[zone] = zone_dist.get(zone, 0) + 1
            if pod.status.phase != "Running":
                logging.warning(f"{pod.metadata.name} of {svc} not Running")
        if len(zone_dist) < 2:
            logging.warning(f"Service {svc} not balanced across zones: {zone_dist}")

def full_health_check():
    logging.info("=== Health Check Start ===")
    check_node_health()
    check_service_health()
    logging.info("=== Health Check End ===")

# ========== VM POWER CONTROL ==========
def ssh_shutdown_vm(ip_address):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip_address, username=SSH_USER, key_filename=SSH_KEY_PATH)
        ssh.exec_command("sudo shutdown -h now")
        ssh.close()
        logging.info(f"Shutdown command sent to VM at {ip_address}")
    except Exception as e:
        logging.error(f"SSH shutdown failed for {ip_address}: {e}")

def libvirt_power_on(vm_name):
    try:
        conn = libvirt.open("qemu:///system")
        dom = conn.lookupByName(vm_name)
        dom.create()
        conn.close()
        logging.info(f"Powered on {vm_name}")
    except Exception as e:
        logging.error(f"Libvirt error for {vm_name}: {e}")

def power_off_node(node_name):
    ip = NODE_VM_MAP[node_name]["ip"]
    ssh_shutdown_vm(ip)

def power_on_node(node_name):
    vm_name = NODE_VM_MAP[node_name]["vm_name"]
    libvirt_power_on(vm_name)

# ========== ZONE FUNCTIONS ==========
def get_nodes_by_zone():
    zone_map = {}
    for node, info in NODE_VM_MAP.items():
        zone = info["zone"]
        zone_map.setdefault(zone, []).append(node)
    return zone_map

# ========== FAILURE SIMULATION ==========
def simulate_random_node_failure(delay=10):
    node = random.choice(list(NODE_VM_MAP.keys()))
    logging.info(f"Simulating node failure: {node}")
    power_off_node(node)
    time.sleep(delay)
    power_on_node(node)

def simulate_random_zone_failure(delay_per_node=5, downtime=10):
    zone_map = get_nodes_by_zone()
    zone = random.choice(list(zone_map.keys()))
    nodes = zone_map[zone]
    logging.info(f"Simulating zone failure: {zone}")

    for node in nodes:
        power_off_node(node)
        time.sleep(delay_per_node)

    time.sleep(downtime)

    for node in nodes:
        power_on_node(node)
        time.sleep(delay_per_node)

# ========== ENTRY POINT ==========
if __name__ == "__main__":
    full_health_check()
    simulate_random_node_failure()
    simulate_random_zone_failure()
    full_health_check()
