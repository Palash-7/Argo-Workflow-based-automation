import subprocess

# Load zone configuration from file
def load_zone_config(file_path='zone-config.txt'):
    zone_map = {}
    with open(file_path, 'r') as f:
        for line in f:
            if ':' in line:
                zone, nodes = line.strip().split(':')
                for node in nodes.split(','):
                    zone_map[node.strip().lower()] = zone.strip()
    return zone_map

# Get list of current node names from kubectl
def get_k8s_nodes():
    result = subprocess.run(['kubectl', 'get', 'nodes', '-o', 'name'], capture_output=True, text=True)
    nodes = result.stdout.strip().split('\n')
    return [node.replace('node/', '') for node in nodes if node]

# Apply zone label to each node
def label_nodes(zone_map):
    nodes = get_k8s_nodes()
    for node in nodes:
        node_key = node.lower()
        if node_key in zone_map:
            zone = zone_map[node_key]
            label_cmd = ['kubectl', 'label', 'node', node, f'topology.kubernetes.io/zone={zone}', '--overwrite']
            print(f"Labeling {node} with zone {zone}...")
            subprocess.run(label_cmd)
        else:
            print(f"⚠️  Node {node} not found in zone-config.txt — skipping.")

if __name__ == '__main__':
    print("🔄 Starting topology zone labeling from zone-config.txt...")
    zone_mapping = load_zone_config()
    label_nodes(zone_mapping)
    print("✅ Labeling complete.")
