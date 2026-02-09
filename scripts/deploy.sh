#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════
#  HYDRA ENGINE — One-Command VM Deployment
#
#  Usage:
#    curl -sSL https://raw.githubusercontent.com/YOUR_USER/hydra/main/scripts/deploy.sh | bash
#
#  Or after cloning:
#    chmod +x scripts/deploy.sh && ./scripts/deploy.sh
#
#  Tested on: Ubuntu 22.04/24.04, Debian 12, Amazon Linux 2023
# ══════════════════════════════════════════════════════════

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[HYDRA]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

INSTALL_DIR="/opt/hydra"
REPO_URL="${HYDRA_REPO:-https://github.com/YOUR_USER/hydra.git}"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║       HYDRA ENGINE — VM Deployment       ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Install Docker if needed ──
if ! command -v docker &> /dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    sudo systemctl enable docker
    sudo systemctl start docker
    log "Docker installed ✓"
else
    log "Docker already installed ✓"
fi

# ── Step 2: Install Docker Compose if needed ──
if ! docker compose version &> /dev/null; then
    log "Installing Docker Compose..."
    sudo apt-get update -qq && sudo apt-get install -y -qq docker-compose-plugin
    log "Docker Compose installed ✓"
else
    log "Docker Compose already installed ✓"
fi

# ── Step 3: Install Git if needed ──
if ! command -v git &> /dev/null; then
    log "Installing Git..."
    sudo apt-get update -qq && sudo apt-get install -y -qq git
fi

# ── Step 4: Clone or pull repo ──
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    log "Cloning HYDRA repository..."
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$USER:$USER" "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── Step 5: Configure environment ──
if [ ! -f "$INSTALL_DIR/.env" ]; then
    warn "No .env file found. Creating from template..."
    cp .env.example .env
    echo ""
    echo -e "${YELLOW}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  IMPORTANT: Edit your .env file with API keys   ║${NC}"
    echo -e "${YELLOW}║                                                  ║${NC}"
    echo -e "${YELLOW}║  nano /opt/hydra/.env                            ║${NC}"
    echo -e "${YELLOW}║                                                  ║${NC}"
    echo -e "${YELLOW}║  Required for full functionality:                ║${NC}"
    echo -e "${YELLOW}║  - ALPACA_API_KEY (paper trading)                ║${NC}"
    echo -e "${YELLOW}║  - TELEGRAM_BOT_TOKEN (alerts)                   ║${NC}"
    echo -e "${YELLOW}║  - FRED_API_KEY (macro data)                     ║${NC}"
    echo -e "${YELLOW}║                                                  ║${NC}"
    echo -e "${YELLOW}║  All are FREE. See .env.example for signup URLs. ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
fi

# ── Step 6: Create data directory ──
mkdir -p "$INSTALL_DIR/data"

# ── Step 7: Build and launch ──
log "Building Docker images..."
docker compose build --no-cache

log "Starting HYDRA..."
docker compose up -d

# ── Step 8: Wait for healthy ──
log "Waiting for services to start..."
sleep 10

if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    log "Backend healthy ✓"
else
    warn "Backend still starting... check: docker compose logs backend"
fi

if curl -sf http://localhost > /dev/null 2>&1; then
    log "Frontend healthy ✓"
else
    warn "Frontend still starting... check: docker compose logs frontend"
fi

# ── Step 9: Setup systemd service for auto-start on reboot ──
sudo tee /etc/systemd/system/hydra.service > /dev/null <<EOF
[Unit]
Description=HYDRA Trading Engine
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=$USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable hydra.service
log "Auto-start on reboot configured ✓"

# ── Done ──
VM_IP=$(curl -sf ifconfig.me 2>/dev/null || echo "YOUR_VM_IP")

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            HYDRA ENGINE — DEPLOYED ✓                ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║  Dashboard:  http://${VM_IP}                   ║${NC}"
echo -e "${GREEN}║  API:        http://${VM_IP}:8000/api/health   ║${NC}"
echo -e "${GREEN}║  Signals:    http://${VM_IP}:8000/api/signals  ║${NC}"
echo -e "${GREEN}║  WebSocket:  ws://${VM_IP}:8000/ws             ║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}║  Logs:       docker compose logs -f                  ║${NC}"
echo -e "${GREEN}║  Stop:       docker compose down                     ║${NC}"
echo -e "${GREEN}║  Update:     git pull && docker compose up -d --build║${NC}"
echo -e "${GREEN}║                                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
