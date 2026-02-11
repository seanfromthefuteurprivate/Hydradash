#!/bin/bash
set -e

REPO_URL="https://github.com/seanfromthefuteurprivate/Hydradash.git"
INSTALL_DIR="/opt/hydra"
SERVICE_NAME="hydra"

echo "══════════════════════════════════════════════════════════════════════════════"
echo "  HYDRA ENGINE DEPLOYMENT"
echo "══════════════════════════════════════════════════════════════════════════════"

if ! command -v docker &> /dev/null; then
    echo "[1/6] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker $USER
else
    echo "[1/6] Docker already installed"
fi

if ! docker compose version &> /dev/null; then
    echo "[2/6] Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    echo "[2/6] Docker Compose already installed"
fi

echo "[3/6] Setting up repository..."
sudo mkdir -p $INSTALL_DIR
sudo chown -R $USER:$USER $INSTALL_DIR

if [ -d "$INSTALL_DIR/.git" ]; then
    cd $INSTALL_DIR && git pull origin main
else
    git clone $REPO_URL $INSTALL_DIR
    cd $INSTALL_DIR
fi

echo "[4/6] Setting up environment..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp $INSTALL_DIR/.env.example $INSTALL_DIR/.env 2>/dev/null || echo "Create .env manually"
fi
mkdir -p $INSTALL_DIR/data

echo "[5/6] Building and starting containers..."
cd $INSTALL_DIR
docker compose build
docker compose up -d

echo "[6/6] Creating systemd service..."
sudo tee /etc/systemd/system/hydra.service > /dev/null << 'SVCEOF'
[Unit]
Description=HYDRA Trading Engine
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/hydra
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable hydra.service

echo ""
echo "HYDRA DEPLOYED: http://$(hostname -I | awk '{print $1}')"
echo "Edit API keys: $INSTALL_DIR/.env"
