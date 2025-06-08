#!/usr/bin/env python3
import random
import time
import logging
import os
import sys
import traceback
import socket
import subprocess
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
import argparse

# ───── Configure logging to both /app/logs and stdout ─────
LOG_DIR = "/app/logs"
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    print(f"Log directory created/verified: {LOG_DIR}")
except Exception as e:
    print(f"WARNING: Could not create log directory {LOG_DIR}: {e}")

log_formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Console handler (so that Argo sees it in pod logs)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

# File handler (writes to /app/logs/rack_resilience_simulation.log)
try:
    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "rack_resilience_simulation.log"))
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
    print("File logging configured successfully")
except Exception as e:
    print(f"WARNING: Could not set up file logging: {e}")
    # Continue without file logging

# ───── Load Kubernetes config (in‐cluster, or fallback to ~/.kube/config) ─────
try:
    config.load_incluster_config()
    logging.info("Loaded in-cluster Kubernetes config")
except Exception as e:
    logging.info(f"In-cluster config failed ({e}); falling back to kubeconfig")
    try:
        config.load_kube_config()
        logging.info("Loaded kubeconfig from file")
    except Exception as e2:
        logging.error(f"Failed to load kubeconfig: {e2}")
        sys.exit(1)

v1 = client.CoreV1Api()

# Node ↔ Zone map - map node names to their rack/zone
NODE_ZONE_MAP = {
    "master-m001": "R1",
    "worker-w001": "R1",
    "worker-w002": "R1",
    "master-m002": "R2",
    "worker-w003": "R2",
    "worker-w004": "R2",
    "master-m003": "R3",
    "worker-w005": "R3",
    "worker-w006": "R3",
}

CRITICAL_SERVICES = ["etcd-sim", "postgres-sim", "redis-sim", "nginx-sim", "auth-sim"]

# Get current hostname
def get_current_node():
    """Get the name of the node where this container is running"""
    hostname = socket.gethostname()
    logging.info(f"Running on host: {hostname}")
    # Some Kubernetes pods get node name as hostname, otherwise we need to check env vars
    if hostname in NODE_ZONE_MAP:
        return hostname
    
    # Try to get from downward API if available (would need to be set in the pod spec)
    node_name = os.environ.get("NODE_NAME")
    if node_name:
        return node_name
        
    # Fallback - assume we're on master-m003 as that's where workflows run
    return "master-m003"

CURRENT_NODE = get_current_node()
CURRENT_ZONE = NODE_ZONE_MAP.get(CURRENT_NODE)
logging.info(f"Detected current node: {CURRENT_NODE}, zone: {CURRENT_ZONE}")

# ───── Health‐check functions ─────
def check_node_health():
    try:
        nodes = v1.list_node().items
    except ApiException as e:
        logging.error(f"Failed to list nodes: {e}")
        return

    for node in nodes:
        node_name = node.metadata.name
        for condition in node.status.conditions:
            if condition.type == "Ready" and condition.status != "True":
                logging.warning(f"Node {node_name} is not Ready")
            elif condition.type == "Ready":
                logging.info(f"Node {node_name} is Ready")

def check_service_health():
    for svc in CRITICAL_SERVICES:
        try:
            pods = v1.list_pod_for_all_namespaces(label_selector=f"app={svc}").items
        except ApiException as e:
            logging.error(f"Failed to list pods for service {svc}: {e}")
            continue

        if not pods:
            logging.warning(f"No pods found for {svc}")
            continue

        zone_dist = {}
        for pod in pods:
            node_name = pod.spec.node_name
            if not node_name:
                zone = "unknown"
            else:
                try:
                    node = v1.read_node(node_name)
                    zone = node.metadata.labels.get("topology.kubernetes.io/zone", "unknown")
                except ApiException:
                    zone = "unknown"
            zone_dist[zone] = zone_dist.get(zone, 0) + 1
            if pod.status.phase != "Running":
                logging.warning(f"Pod {pod.metadata.name} for {svc} is not Running")

        logging.info(f"Service {svc} zone distribution: {zone_dist}")
        if len(zone_dist) < 2:
            logging.warning(f"Service {svc} is not resilient across zones")

def log_pods_wide_output():
    """Run kubectl get pods -o wide and log the output"""
    try:
        logging.info("============ DETAILED POD INFORMATION ============")
        logging.info("Running 'kubectl get pods -o wide' to show detailed pod placement:")
        result = subprocess.run(
            ["kubectl", "get", "pods", "-o", "wide", "--all-namespaces"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        # Split the output by lines and log each line
        lines = result.stdout.strip().split('\n')
        for line in lines:
            logging.info(f"  {line}")
        
        # Print pod count by node
        logging.info("\nPod distribution by node:")
        pod_count_cmd = ["kubectl", "get", "pods", "--all-namespaces", "-o", "wide", "--no-headers"]
        result = subprocess.run(pod_count_cmd, capture_output=True, text=True, check=True)
        
        # Count pods per node
        pods_by_node = {}
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 8:  # Ensure we have enough columns
                    node = parts[7]  # Node name is in column 8
                    pods_by_node[node] = pods_by_node.get(node, 0) + 1
        
        # Display the count
        for node, count in pods_by_node.items():
            logging.info(f"  Node {node}: {count} pods")
            
        # Log header for services we're interested in
        logging.info("\nFiltering for simulation services:")
        
        # Run a filtered query to only show our simulation pods
        filter_cmd = ["kubectl", "get", "pods", "-o", "wide"]
        grep_patterns = "|".join(CRITICAL_SERVICES)
        grep_cmd = ["grep", "-E", grep_patterns]
        
        ps1 = subprocess.Popen(filter_cmd, stdout=subprocess.PIPE)
        ps2 = subprocess.Popen(grep_cmd, stdin=ps1.stdout, stdout=subprocess.PIPE, text=True)
        ps1.stdout.close()
        output = ps2.communicate()[0]
        
        # Log the filtered output
        filtered_lines = output.strip().split('\n')
        for line in filtered_lines:
            if line:  # Skip empty lines
                logging.info(f"  {line}")
                
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running kubectl: {e}")
        logging.error(f"Error output: {e.stderr}")
    except Exception as e:
        logging.error(f"Error getting pod information: {e}")

def log_node_status_detailed():
    """Log detailed node status with custom formatting for taints and cordon state"""
    try:
        logging.info("\n============ DETAILED NODE STATUS ============")
        
        # Get basic node information
        logging.info("Basic Node Information (kubectl get nodes -o wide):")
        nodes_cmd = ["kubectl", "get", "nodes", "-o", "wide"]
        nodes_result = subprocess.run(nodes_cmd, capture_output=True, text=True, check=True)
        for line in nodes_result.stdout.strip().split('\n'):
            logging.info(f"  {line}")
            
        # Get node status with custom labels
        logging.info("\nEnhanced Node Status (with taint and cordon indicators):")
        logging.info("  NAME                STATUS    ROLES           ZONE   CORDONED   TAINTS")
        
        # Get node list
        node_list_cmd = ["kubectl", "get", "nodes", "-o", "name"]
        node_list_result = subprocess.run(node_list_cmd, capture_output=True, text=True, check=True)
        
        for node_ref in node_list_result.stdout.strip().split('\n'):
            if not node_ref:
                continue
                
            node_name = node_ref.replace('node/', '')
            
            # Get node details
            node_cmd = ["kubectl", "get", "node", node_name, "-o", "jsonpath={.metadata.labels.topology\\.kubernetes\\.io/zone},{.spec.unschedulable},{.status.conditions[?(@.type==\"Ready\")].status}"]
            node_result = subprocess.run(node_cmd, capture_output=True, text=True, check=True)
            
            node_info = node_result.stdout.split(',')
            zone = node_info[0] if len(node_info) > 0 else "unknown"
            unschedulable = node_info[1] == "true" if len(node_info) > 1 else False
            ready = node_info[2] == "True" if len(node_info) > 2 else False
            
            # Get role labels
            role_cmd = ["kubectl", "get", "node", node_name, "-o", "jsonpath={.metadata.labels.node-role\\.kubernetes\\.io/.*}"]
            role_result = subprocess.run(role_cmd, capture_output=True, text=True, check=True)
            role = "control-plane" if "control-plane" in role_result.stdout else "worker"
            
            # Get taints
            taint_cmd = ["kubectl", "get", "node", node_name, "-o", "jsonpath={.spec.taints[*].key}"]
            taint_result = subprocess.run(taint_cmd, capture_output=True, text=True, check=True)
            taints = taint_result.stdout.split()
            
            # Format status string
            status = "Ready" if ready else "NotReady"
            cordoned = "YES" if unschedulable else "No"
            
            # Format taints string
            taint_str = ", ".join(taints) if taints else "None"
            
            # Add warning indicators
            status_indicator = "⚠️" if not ready else "✓"
            cordoned_indicator = "⚠️" if unschedulable else ""
            taint_indicator = "⚠️" if "simulated-failure" in taint_str else ""
            
            # Log formatted line
            logging.info(f"  {node_name:<15} {status:<7}{status_indicator} {role:<14} {zone:<5} {cordoned:<8}{cordoned_indicator} {taint_str} {taint_indicator}")
            
        # Add a legend
        logging.info("\nLegend:")
        logging.info("  ✓ = Node is Ready")
        logging.info("  ⚠️ = Warning indicator (NotReady, Cordoned, or has simulated-failure taint)")
        
    except Exception as e:
        logging.error(f"Error getting detailed node status: {e}")

def full_health_check():
    logging.info("Starting full health check")
    
    # Add detailed node status first for better visibility
    log_node_status_detailed()
    
    # Log kubectl get pods -o wide output
    log_pods_wide_output()
    
    # Run standard checks
    check_node_health()
    check_service_health()
    
    logging.info("Completed full health check")

# ───── Check if we have permissions to modify nodes ─────
def have_node_modification_permissions():
    """Check if we have permissions to modify node state"""
    try:
        logging.info("Checking if we have permissions to modify nodes...")
        # First just try listing nodes
        nodes = v1.list_node()
        if not nodes.items:
            logging.warning("No nodes found in cluster")
            return False
            
        # Try get a node reference for testing
        test_node = None
        for node in nodes.items:
            # Skip the node we're running on
            if node.metadata.name != CURRENT_NODE:
                test_node = node.metadata.name
                break
        
        if not test_node:
            test_node = nodes.items[0].metadata.name
            
        logging.info(f"Testing permissions using node: {test_node}")
        
        # Try a dry run of cordoning the node
        v1.patch_node(
            name=test_node,
            body={"spec": {"unschedulable": True}},
            dry_run="All"
        )
        
        logging.info("Permission check successful - we can modify nodes")
        return True
    except ApiException as e:
        logging.error(f"Permission check failed: {e}")
        if e.status == 403:
            logging.error("The service account does not have sufficient permissions to modify nodes")
            logging.error("RBAC configuration needed:")
            logging.error("""
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-admin
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "update", "patch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argo-node-admin
subjects:
- kind: ServiceAccount
  name: argo-workflow
  namespace: argo
roleRef:
  kind: ClusterRole
  name: node-admin
  apiGroup: rbac.authorization.k8s.io
            """)
        return False
    except Exception as e:
        logging.error(f"Error checking permissions: {e}")
        return False

# ───── Mock implementation (when we don't have node permissions) ─────
def mock_power_off_node(node_name: str):
    """Simulate node failure without actually modifying the node"""
    logging.warning(f"MOCK MODE: Simulating node failure for {node_name} (no actual changes)")
    logging.warning("This is a mock implementation due to insufficient permissions")
    # Sleep briefly to simulate the operation taking time
    time.sleep(1)
    logging.info(f"MOCK: Node {node_name} is now 'down' (simulation only)")

def mock_power_on_node(node_name: str):
    """Simulate node recovery without actually modifying the node"""
    logging.warning(f"MOCK MODE: Simulating node recovery for {node_name} (no actual changes)")
    logging.warning("This is a mock implementation due to insufficient permissions")
    # Sleep briefly to simulate the operation taking time
    time.sleep(1)
    logging.info(f"MOCK: Node {node_name} is now 'up' (simulation only)")

# ───── Real Kubernetes API implementation ─────
def api_power_off_node(node_name: str):
    """Actually cordon and taint the node to simulate failure"""
    try:
        logging.info(f"Simulating node failure for {node_name} using Kubernetes API")
        
        # Check that we're not trying to take down our own node
        if node_name == CURRENT_NODE:
            logging.warning(f"Refusing to power off the node this workflow is running on ({node_name})")
            return
            
        # Get current node state
        node = v1.read_node(name=node_name)
        
        # Step 1: Cordon the node (mark as unschedulable)
        v1.patch_node(
            name=node_name,
            body={
                "spec": {"unschedulable": True}
            }
        )
        logging.info(f"Node {node_name} cordoned")
        
        # Step 2: Add a NoExecute taint to evict pods
        # Check if the taint already exists
        existing_taints = node.spec.taints or []
        
        # Check if our taint already exists
        taint_exists = False
        for taint in existing_taints:
            if taint.key == "simulated-failure" and taint.effect == "NoExecute":
                taint_exists = True
                logging.info(f"Node {node_name} already has simulated-failure taint, skipping tainting step")
                break
        
        # Only add the taint if it doesn't exist
        if not taint_exists:
            # Add our taint to the existing ones
            new_taints = existing_taints + [{
                "effect": "NoExecute",
                "key": "simulated-failure", 
                "value": "true"
            }]
            
            v1.patch_node(
                name=node_name,
                body={
                    "spec": {
                        "taints": new_taints
                    }
                }
            )
            
            logging.info(f"Node {node_name} tainted with NoExecute")
        
        logging.info(f"Node {node_name} powered off (delay 5s)")
        
    except ApiException as e:
        logging.error(f"Failed to simulate failure for node {node_name}: {e}")
        raise

def api_power_on_node(node_name: str):
    """Actually remove the taint and uncordon the node"""
    try:
        logging.info(f"Simulating node recovery for {node_name} using Kubernetes API")
        
        # Step 1: Fetch current node data
        node = v1.read_node(name=node_name)
        
        # Step 2: Remove our simulation taint while preserving others
        if node.spec.taints:
            taints = [t for t in node.spec.taints if t.key != "simulated-failure"]
            v1.patch_node(
                name=node_name,
                body={"spec": {"taints": taints}}
            )
            logging.info(f"Removed simulated-failure taint from node {node_name}")
        
        # Step 3: Uncordon the node (mark as schedulable)
        v1.patch_node(
            name=node_name,
            body={
                "spec": {"unschedulable": False}
            }
        )
        logging.info(f"Node {node_name} uncordoned and ready")
        
    except ApiException as e:
        logging.error(f"Failed to recover node {node_name}: {e}")
        raise

# Pick the appropriate implementation based on permissions
if have_node_modification_permissions():
    logging.info("Using real Kubernetes API for node control")
    power_off_node = api_power_off_node
    power_on_node = api_power_on_node
else:
    logging.warning("USING MOCK MODE for node control due to insufficient permissions")
    power_off_node = mock_power_off_node
    power_on_node = mock_power_on_node

def get_nodes_by_zone():
    zone_map = {}
    for node, zone in NODE_ZONE_MAP.items():
        zone_map.setdefault(zone, []).append(node)
    return zone_map

# ───── Failure simulation ─────
def simulate_random_node_failure(delay: int = 10, stabilization_time: int = 30):
    try:
        # Choose from nodes not in our zone
        safe_nodes = [node for node, zone in NODE_ZONE_MAP.items() if node != CURRENT_NODE]
        if not safe_nodes:
            logging.error("No safe nodes available for simulation")
            return
            
        node = random.choice(safe_nodes)
        logging.info(f"Simulating node failure: {node}")
        power_off_node(node)
        logging.info(f"Node {node} down for {delay} seconds")
        
        # Add stabilization time to allow pods to be evicted and rescheduled
        logging.info(f"Waiting {stabilization_time} seconds for the cluster to stabilize before health check...")
        time.sleep(stabilization_time)
        
        logging.info("Running health check after node power off")
        full_health_check()
        time.sleep(delay)
        logging.info("Running health check before node power on")
        full_health_check()
        power_on_node(node)
        logging.info(f"Node {node} has been powered back on")
        
        # Add stabilization time after recovery
        logging.info(f"Waiting {stabilization_time} seconds for the cluster to stabilize after recovery...")
        time.sleep(stabilization_time)
        
        logging.info("Running final health check")
        full_health_check()
        
    except Exception as e:
        logging.error(f"Error in node failure simulation: {e}")
        logging.error(traceback.format_exc())

def simulate_random_zone_failure(delay_per_node: int = 5, downtime: int = 10, stabilization_time: int = 60):
    try:
        zone_map = get_nodes_by_zone()
        
        # Exclude the zone containing the current node
        safe_zones = [zone for zone in zone_map.keys() if zone != CURRENT_ZONE]
        if not safe_zones:
            logging.error(f"No safe zones available for rack simulation (current node {CURRENT_NODE} in zone {CURRENT_ZONE})")
            return
        
        # Log which zones are safe to simulate failures on    
        logging.info(f"Current node: {CURRENT_NODE} in zone: {CURRENT_ZONE}")
        logging.info(f"Safe zones for rack simulation: {safe_zones}")
            
        zone = random.choice(safe_zones)
        nodes = zone_map[zone]
        logging.info(f"Simulating full rack (zone) failure: {zone} with nodes: {nodes}")
        
        # Add a double-check to make sure no node in the current zone gets shut down
        nodes_to_shutoff = [node for node in nodes if NODE_ZONE_MAP.get(node) != CURRENT_ZONE]
        skipped = set(nodes) - set(nodes_to_shutoff)
        if skipped:
            logging.warning(f"Skipping nodes {skipped} as they are in the same zone as the current node")
        
        for node in nodes_to_shutoff:
            try:
                power_off_node(node)
                logging.info(f"Node {node} powered off (delay {delay_per_node}s)")
                time.sleep(delay_per_node)
            except Exception as e:
                logging.error(f"Error shutting down node {node}: {e}")
                logging.error(traceback.format_exc())
                # Continue with other nodes, don't abort the whole simulation
        
        # Add stabilization time to allow pods to be evicted and rescheduled
        logging.info(f"Waiting {stabilization_time} seconds for the cluster to stabilize before health check...")
        time.sleep(stabilization_time)
            
        logging.info("Running health check after rack power off")
        full_health_check()
        logging.info(f"Zone {zone} remains down for {downtime} seconds")
        time.sleep(downtime)
        logging.info("Running health check before rack power on")
        full_health_check()
        
        for node in nodes_to_shutoff:
            try:
                power_on_node(node)
                logging.info(f"Node {node} powered on (delay {delay_per_node}s)")
                time.sleep(delay_per_node)
            except Exception as e:
                logging.error(f"Error recovering node {node}: {e}")
                logging.error(traceback.format_exc())
                # Continue with other nodes
        
        # Add stabilization time after recovery
        logging.info(f"Waiting {stabilization_time} seconds for the cluster to stabilize after recovery...")
        time.sleep(stabilization_time)
        
        logging.info("Running final health check")
        full_health_check()
            
        logging.info(f"Rack {zone} has been fully restored")
    except Exception as e:
        logging.error(f"Error in zone failure simulation: {e}")
        logging.error(traceback.format_exc())

# ───── Main entry point ─────
if __name__ == "__main__":
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="Rack Resiliency Simulation Tool")
        parser.add_argument("action", choices=["health-check", "simulate-node", "simulate-rack", "recover-node", "recover-rack"], 
                           help="Action to perform")
        parser.add_argument("--stabilization-time", type=int, default=60,
                           help="Time (in seconds) to wait for the cluster to stabilize after a failure")
        parser.add_argument("--downtime", type=int, default=10,
                           help="Duration (in seconds) to keep the nodes down")
        args = parser.parse_args()
        
        action = args.action
        stabilization_time = args.stabilization_time
        downtime = args.downtime
        
        logging.info(f"Action received: {action}")
        logging.info(f"Stabilization time: {stabilization_time} seconds")

        if action == "health-check":
            full_health_check()
        elif action == "simulate-node":
            simulate_random_node_failure(stabilization_time=stabilization_time)
        elif action == "simulate-rack":
            simulate_random_zone_failure(downtime=downtime, stabilization_time=stabilization_time)
        elif action in ("recover-node", "recover-rack"):
            logging.info(f"Recovery action ({action}) is a no-op.")
        else:
            logging.error(f"Unknown action: {action}")
            sys.exit(1)
    except Exception as e:
        logging.error(f"Unhandled exception: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)
