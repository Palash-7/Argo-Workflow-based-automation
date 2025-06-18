# Kubernetes Rack Resiliency Testing Framework with Argo Workflows

![Python](https://img.shields.io/badge/Python-85.7%25-blue)
![Shell](https://img.shields.io/badge/Shell-11.1%25-green)
![Dockerfile](https://img.shields.io/badge/Dockerfile-3.2%25-orange)

A comprehensive framework for testing system resilience through rack-level failure simulation in Kubernetes clusters using Argo Workflows. This project focuses on validating rack resiliency by testing the system's ability to continue operating during rack-level failures in a Kubernetes cluster environment (HPC).

## Repository Structure

This repository is organized as follows:

- [Automation_Scripts](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/Automation_Scripts) - Scripts for automating chaos testing and workflow execution
- [Critical_Services](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/Critical_Services) - Definitions and configurations for critical services to be tested
- [Logs](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/Logs) - Log files generated during test runs
- [k8s_cluster](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/k8s_cluster) - Kubernetes cluster configuration files

## Overview

This framework is designed to test application resilience in Kubernetes environments by simulating different types of failures at the rack level. Key features include:

- **Node Failure Simulation**: Simulates single node failures by cordoning and tainting nodes.
- **Rack Failure Simulation**: Simulates failures of entire racks/zones of nodes.
- **Automated Recovery**: Automatically recovers nodes after a configurable downtime.
- **Detailed Monitoring**: Provides comprehensive logging of cluster state before, during, and after failures.
- **Zone-aware Testing**: Ensures proper testing of multi-zone resilience.
- **Argo Workflow Integration**: All tests are orchestrated using Argo Workflows for reliability and reproducibility.

## Architecture

The framework uses the following components:

1. **Kubernetes API**: For node cordoning, tainting, and monitoring.
2. **Argo Workflows**: Orchestrates the chaos testing workflows.
3. **Python Scripts**: Handle the actual simulation logic.
4. **Custom Docker Container**: Encapsulates all dependencies.
5. **RBAC**: Provides necessary permissions for node operations.

The system works by:
1. Identifying target nodes based on zone/rack assignment
2. Cordoning and tainting nodes to simulate failures
3. Monitoring application behavior during the simulated failure
4. Uncordoning and untainting nodes to simulate recovery
5. Verifying proper application recovery

## Prerequisites

- Vagrant installed in your system working directory
- kubectl configured for your cluster
- Docker for building the simulation container
- Argo Workflows installed in your cluster
- Proper RBAC permissions for node management

## Installation

### Setting Up the Cluster
Install Vagrant in your working directory
For detailed cluster setup instructions, please refer to the [k8s_cluster](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/k8s_cluster) directory in the repository.

Label your nodes with zones to simulate racks:
```bash
# Example: Label nodes with zones
python3 label-nodes-by-zones.py
```

### Installing Argo Workflows

Install Argo Workflows in your cluster:

```bash
# Create namespace
kubectl create namespace argo

# Install Argo Workflows
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.4.0/install.yaml

# Install the Argo CLI
curl -sLO https://github.com/argoproj/argo-workflows/releases/download/v3.4.0/argo-linux-amd64.gz
gunzip argo-linux-amd64.gz
chmod +x argo-linux-amd64
sudo mv argo-linux-amd64 /usr/local/bin/argo
```

## Running RR Tests

Check the [Automation_Scripts](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/Automation_Scripts) directory for the available test workflows and scripts.
```

### Node Failure Simulation

To simulate a single node failure:

```bash
# Apply the node failure workflow from the Automation_Scripts directory
argo submit -n argo <path-to-workflow-yaml> --watch
```

This will:
1. Run a health check
2. Simulate a node failure (cordon + taint)
3. Wait for the specified time
4. Recover the node
5. Run a final health check

### Rack (Zone) Failure Simulation

To simulate a rack/zone failure:

```bash
# Using Argo CLI
argo submit -n argo <path-to-rack-workflow-yaml> --watch
```

## Monitoring Results

You can monitor your chaos tests in several ways:

### Argo UI

Access the Argo UI to monitor workflow progress:

```bash
# Port forward the Argo UI
kubectl port-forward svc/argo-server -n argo 2746:2746

# Access in browser
# https://localhost:2746
```
### Logs
Visible in Argo UI  -> under Argo namespace -> go to workfow -> LOGS tab
To view the Argo UI :
Run in the host terminal:
```
kubectl -n argo port-forward svc/argo-server 2746:2746
```
Go to: 
```
https://localhost:2746/
```

Will be stored inside master-m003 node inside the directory argo-logs within subfolders for each DAG template logs under the name rack_resilience_simulation.log 


Some sample Log files that were generated are stored in the [Logs](https://github.com/Palash-7/Argo-Workflow-based-automation/tree/main/Logs) directory of the repository.

## Detailed Node and Pod Information

During health checks, the system logs detailed information:

1. **Node Status**:
   - Basic node information with `kubectl get nodes -o wide`
   - Enhanced status with cordoned state and taints
   - Warning indicators for problem states

2. **Pod Information**:
   - All pods with `kubectl get pods -o wide --all-namespaces`
   - Pod distribution by node
   - Service-specific pod details
   - Zone distribution analysis

## Cleanup After Interruptions

If a chaos test is interrupted, nodes might be left cordoned or tainted. To clean up:

```bash
# Script to clean up ALL nodes at once
for NODE in $(kubectl get nodes -o name); do
  kubectl uncordon ${NODE}
  kubectl taint nodes ${NODE} simulated-failure- 2>/dev/null || true
  echo "Cleaned up ${NODE}"
done
```

## Restarting Services

To restart all deployments (which will restart all pods):

```bash
# Restart all deployments
kubectl get deployments --all-namespaces -o name | xargs -I {} kubectl rollout restart {}

# Or restart specific simulation services from the Critical_Services directory
kubectl rollout restart deployment <service-name>
```

## Troubleshooting

### Common Issues

#### Nodes Not Recovering

If nodes are stuck in an unschedulable state:

```bash
# Check node status
kubectl get nodes

# Manually uncordon a node
kubectl uncordon <node-name>

# Remove taints
kubectl taint nodes <node-name> simulated-failure-
```

#### Permission Issues

If you see errors about insufficient permissions:

```bash
# Check RBAC binding
kubectl describe clusterrolebinding argo-node-admin

# Verify the service account exists
kubectl get sa -n argo argo-workflow
```

#### Pod Distribution Issues

If services aren't properly distributed across zones after recovery:

```bash
# Restart services to trigger rebalancing
kubectl rollout restart deployments

# Check distribution
kubectl get pods -o wide
```
