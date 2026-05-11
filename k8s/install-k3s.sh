#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  PlacewareBot — K3s Setup & Image Build Script
#  Run this ON YOUR UBUNTU VM as a non-root user with sudo access.
#  Usage: chmod +x install-k3s.sh && ./install-k3s.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

NAMESPACE="placeware"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # workspace root

# ── Colour helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warning() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ───────────────────────────────────────────────────────────────────────────
# STEP 1 — Install K3s (lightweight Kubernetes)
# ───────────────────────────────────────────────────────────────────────────
info "Installing K3s..."
if command -v k3s &>/dev/null; then
  warning "K3s already installed — skipping."
else
  # Installs K3s with the Nginx Ingress controller enabled
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --disable traefik" sh -
  info "K3s installed."
fi

# Make kubectl accessible without sudo for the current user
mkdir -p "$HOME/.kube"
sudo cp /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
export KUBECONFIG="$HOME/.kube/config"
info "kubectl configured."

# ───────────────────────────────────────────────────────────────────────────
# STEP 2 — Install Nginx Ingress Controller
# ───────────────────────────────────────────────────────────────────────────
info "Installing Nginx Ingress Controller..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/cloud/deploy.yaml

info "Waiting for Ingress controller to be ready (up to 120s)..."
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s

info "Nginx Ingress Controller ready."

# ───────────────────────────────────────────────────────────────────────────
# STEP 3 — Install metrics-server (required for HPA)
# ───────────────────────────────────────────────────────────────────────────
info "Installing metrics-server..."
# K3s ships metrics-server as an optional component; enable it via flag
# If already present, this is a no-op
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Patch for single-node clusters that use self-signed certs
kubectl patch deployment metrics-server \
  -n kube-system \
  --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' \
  2>/dev/null || true

info "metrics-server deployed."

# ───────────────────────────────────────────────────────────────────────────
# STEP 4 — Build Docker images on the VM
# ───────────────────────────────────────────────────────────────────────────
info "Building Docker images..."

# Requires Docker installed: sudo apt-get install -y docker.io
if ! command -v docker &>/dev/null; then
  warning "Docker not found. Installing Docker..."
  sudo apt-get update -qq
  sudo apt-get install -y docker.io
  sudo usermod -aG docker "$(whoami)"
  warning "Added $(whoami) to docker group. You may need to log out and back in."
  warning "Re-run this script after logging back in if docker commands fail."
fi

cd "$REPO_DIR"

info "Building placeware-postgres:18 (Postgres + pgvector)..."
docker build -t placeware-postgres:18 ./backend/db/

info "Building placeware-backend:latest (FastAPI)..."
docker build -t placeware-backend:latest ./backend/

info "Building placeware-frontend:latest (React + nginx)..."
docker build -t placeware-frontend:latest ./SynbotUI/

# ───────────────────────────────────────────────────────────────────────────
# STEP 5 — Import images into K3s containerd
# K3s uses its own containerd runtime, not the host Docker daemon.
# Images must be explicitly imported — docker build alone is not enough.
# ───────────────────────────────────────────────────────────────────────────
info "Importing images into K3s containerd..."

import_image() {
  local tag="$1"
  info "  Importing $tag..."
  docker save "$tag" | sudo k3s ctr images import -
}

import_image "placeware-postgres:18"
import_image "placeware-backend:latest"
import_image "placeware-frontend:latest"

info "All images imported."

# ───────────────────────────────────────────────────────────────────────────
# STEP 6 — Apply Kubernetes manifests
# ───────────────────────────────────────────────────────────────────────────
K8S_DIR="$REPO_DIR/k8s"

info "==================================================================="
warning "STOP — Before continuing, fill in all <REPLACE> values in:"
warning "  $K8S_DIR/01-secrets.yaml"
warning "Then press ENTER to continue, or Ctrl+C to abort."
info "==================================================================="
read -r

info "Applying namespace..."
kubectl apply -f "$K8S_DIR/00-namespace.yaml"

info "Applying secrets & config..."
kubectl apply -f "$K8S_DIR/01-secrets.yaml"
kubectl apply -f "$K8S_DIR/02-configmap.yaml"

info "Applying Postgres StatefulSet..."
kubectl apply -f "$K8S_DIR/03-postgres.yaml"

info "Waiting for Postgres pod to be ready (up to 120s)..."
kubectl wait pod \
  -n "$NAMESPACE" \
  --for=condition=ready \
  -l app=postgres \
  --timeout=120s

info "Running database migrations (Job)..."
kubectl apply -f "$K8S_DIR/04-migration-job.yaml"

info "Waiting for migration Job to complete (up to 180s)..."
kubectl wait job/placeware-migrate \
  -n "$NAMESPACE" \
  --for=condition=complete \
  --timeout=180s

info "Deploying backend..."
kubectl apply -f "$K8S_DIR/05-backend.yaml"

info "Applying HPA..."
kubectl apply -f "$K8S_DIR/06-backend-hpa.yaml"

info "Deploying frontend..."
kubectl apply -f "$K8S_DIR/07-frontend.yaml"

info "Applying Ingress..."
kubectl apply -f "$K8S_DIR/08-ingress.yaml"

# ───────────────────────────────────────────────────────────────────────────
# STEP 7 — Status summary
# ───────────────────────────────────────────────────────────────────────────
info "==================================================================="
info "Deployment complete. Current cluster state:"
kubectl get pods,svc,hpa,ingress -n "$NAMESPACE"

echo ""
info "Useful commands:"
echo "  Watch pods in real-time:     kubectl get pods -n $NAMESPACE -w"
echo "  View backend logs:           kubectl logs -n $NAMESPACE -l app=backend --tail=50"
echo "  Check HPA status:            kubectl get hpa -n $NAMESPACE"
echo "  Trigger manual scale test:   kubectl scale deploy/backend -n $NAMESPACE --replicas=5"
echo "  Re-run migrations:           kubectl delete job placeware-migrate -n $NAMESPACE"
echo "                               kubectl apply -f $K8S_DIR/04-migration-job.yaml"
echo "  Redeploy after code change:  (rebuild images, reimport, then:)"
echo "    kubectl rollout restart deployment/backend -n $NAMESPACE"
echo "    kubectl rollout restart deployment/frontend -n $NAMESPACE"
echo ""
info "Access the app at: http://$(hostname -I | awk '{print $1}')"
info "==================================================================="
