#!/usr/bin/env bash
# =============================================================================
# deploy/init-swarm.sh — One-time Docker Swarm + local registry initialisation
#
# Run ONCE on the client server before the first deployment.
# After this, every git push to main triggers a ZERO-DOWNTIME rolling update
# via the GitHub Actions pipeline.
#
# Usage:
#   sudo bash deploy/init-swarm.sh
#
# What it does:
#   1. Initialises Docker Swarm (single-node manager + worker)
#   2. Starts a local image registry at localhost:5000 (images never leave LAN)
#   3. Configures Docker daemon to trust localhost:5000
#   4. Generates a self-signed TLS cert for the server IP
#   5. Builds and pushes the initial images to the local registry
#   6. Deploys the full stack with docker stack deploy
# =============================================================================
set -euo pipefail

# ─── Resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/SynbotUI"

# ─── Colour helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[init-swarm]${NC} $*"; }
warn()  { echo -e "${YELLOW}[init-swarm][WARN]${NC} $*"; }
error() { echo -e "${RED}[init-swarm][ERROR]${NC} $*" >&2; exit 1; }

# ─── Require root ─────────────────────────────────────────────────────────────
[ "$EUID" -eq 0 ] || error "Must run as root: sudo bash deploy/init-swarm.sh"

# ─── Require .env ─────────────────────────────────────────────────────────────
[ -f "$BACKEND_DIR/.env" ] || error "backend/.env not found. Copy .env.example and fill secrets before running."

# ─── 1. Docker Swarm ──────────────────────────────────────────────────────────
if docker info 2>/dev/null | grep -q "Swarm: active"; then
    info "Docker Swarm already active — skipping init."
else
    # Use loopback advertise address for single-node setup (no LAN exposure of swarm port)
    docker swarm init --advertise-addr 127.0.0.1
    info "Docker Swarm initialised (single-node mode)."
fi

# ─── 2. Local image registry at localhost:5000 ────────────────────────────────
if docker ps --filter "name=placeware-registry" --format '{{.Names}}' | grep -q "placeware-registry"; then
    info "Local registry already running."
else
    docker volume create registry_data 2>/dev/null || true
    docker run -d \
        --name placeware-registry \
        --restart always \
        -p 127.0.0.1:5000:5000 \
        -v registry_data:/var/lib/registry \
        registry:2
    info "Local registry started at localhost:5000 (loopback only — not exposed to LAN)."
fi

# ─── 3. Trust localhost:5000 (Docker insecure-registries) ────────────────────
DAEMON_JSON="/etc/docker/daemon.json"
if grep -q "localhost:5000" "$DAEMON_JSON" 2>/dev/null; then
    info "Docker daemon already trusts localhost:5000."
else
    if [ -f "$DAEMON_JSON" ]; then
        # Merge into existing daemon.json preserving existing keys
        python3 - <<EOF
import json, sys
with open('$DAEMON_JSON') as f:
    d = json.load(f)
d.setdefault('insecure-registries', [])
if 'localhost:5000' not in d['insecure-registries']:
    d['insecure-registries'].append('localhost:5000')
with open('$DAEMON_JSON', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
print("Merged insecure-registries into $DAEMON_JSON")
EOF
    else
        echo '{"insecure-registries": ["localhost:5000"]}' > "$DAEMON_JSON"
        info "Created $DAEMON_JSON with insecure-registries."
    fi
    # Reload Docker daemon config (no full restart — avoid killing running containers)
    systemctl reload docker
    info "Docker daemon configured to trust localhost:5000."
fi

# ─── 4. Generate TLS certificate ─────────────────────────────────────────────
SERVER_IP="${SERVER_IP:-$(hostname -I | awk '{print $1}')}"
info "Generating self-signed TLS cert for IP: $SERVER_IP"
bash "$SCRIPT_DIR/gen-tls-cert.sh" "$SERVER_IP" || warn "TLS cert generation failed — frontend HTTPS may not work. Run deploy/gen-tls-cert.sh manually."

# ─── 5. Build and push images to local registry ───────────────────────────────
IMAGE_TAG="init-$(date +%Y%m%d%H%M%S)"
info "Building backend image (tag: $IMAGE_TAG)..."
docker build -t "localhost:5000/placeware-backend:$IMAGE_TAG" "$BACKEND_DIR"
docker push "localhost:5000/placeware-backend:$IMAGE_TAG"
docker tag  "localhost:5000/placeware-backend:$IMAGE_TAG" "localhost:5000/placeware-backend:latest"
docker push "localhost:5000/placeware-backend:latest"
info "Backend image pushed."

info "Building frontend image..."
docker build -t "localhost:5000/placeware-frontend:$IMAGE_TAG" "$FRONTEND_DIR"
docker push "localhost:5000/placeware-frontend:$IMAGE_TAG"
docker tag  "localhost:5000/placeware-frontend:$IMAGE_TAG" "localhost:5000/placeware-frontend:latest"
docker push "localhost:5000/placeware-frontend:latest"
info "Frontend image pushed."

# Build the custom postgres image (not in rolling update — built once)
if ! docker image inspect "placeware-postgres:18" &>/dev/null; then
    info "Building custom postgres image..."
    docker build -t placeware-postgres:18 "$BACKEND_DIR/db"
    info "Postgres image built."
fi

# ─── 6. Deploy the Swarm stack ───────────────────────────────────────────────
info "Deploying Placeware Swarm stack..."
cd "$BACKEND_DIR"
IMAGE_TAG="$IMAGE_TAG" docker stack deploy \
    --with-registry-auth \
    --prune \
    -c docker-compose.swarm.yml \
    placeware

info "Stack deployed. Waiting 20s for services to start..."
sleep 20
docker stack ps placeware --no-trunc

# ─── 7. Health check ─────────────────────────────────────────────────────────
info "Checking backend health (up to 90s)..."
for i in $(seq 1 18); do
    if curl -sf http://localhost:8000/ > /dev/null 2>&1; then
        info "Backend healthy after ${i}x5s."
        break
    fi
    sleep 5
done
curl -f http://localhost:8000/ > /dev/null || warn "Backend health check failed — check: docker service logs placeware_backend"

info "Checking frontend HTTPS health..."
curl -sfkL https://localhost/ > /dev/null && info "Frontend healthy (HTTPS)." || warn "Frontend not responding — check: docker service logs placeware_frontend"

echo ""
echo "========================================================================"
echo "  Placeware Swarm stack is live."
echo ""
echo "  Useful commands:"
echo "    docker stack ps placeware           — service status"
echo "    docker service logs placeware_backend --tail 50 --follow"
echo "    docker service logs placeware_frontend --tail 30"
echo "    docker stack rm placeware            — tear down stack"
echo ""
echo "  From now on, every git push to main triggers a ZERO-DOWNTIME rolling"
echo "  update via GitHub Actions. No further manual steps needed."
echo "========================================================================"
