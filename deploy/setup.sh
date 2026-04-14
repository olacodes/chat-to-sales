#!/usr/bin/env bash
# =============================================================================
# ChatToSales — One-time Server Bootstrap
# Run as root (or with sudo) on a fresh Hetzner Ubuntu 22.04 server.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/setup.sh | bash
#   -- OR --
#   scp deploy/setup.sh root@204.168.201.192:/root/
#   ssh root@204.168.201.192 bash /root/setup.sh
# =============================================================================
set -euo pipefail

APP_USER="deploy"
APP_DIR="/opt/chattosales"

echo "▶ Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

echo "▶ Installing essentials..."
apt-get install -y -qq \
    curl \
    git \
    ufw \
    fail2ban \
    unattended-upgrades \
    ca-certificates \
    gnupg \
    lsb-release

# ── Docker ────────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "▶ Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
else
    echo "   Docker already installed — skipping."
fi

# ── Unprivileged deploy user ──────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    echo "▶ Creating deploy user '$APP_USER'..."
    useradd -m -s /bin/bash "$APP_USER"
    usermod -aG docker "$APP_USER"
    mkdir -p /home/"$APP_USER"/.ssh
    # Copy root's authorized_keys so your existing SSH key works for deploy user
    if [[ -f /root/.ssh/authorized_keys ]]; then
        cp /root/.ssh/authorized_keys /home/"$APP_USER"/.ssh/authorized_keys
        chown -R "$APP_USER":"$APP_USER" /home/"$APP_USER"/.ssh
        chmod 700 /home/"$APP_USER"/.ssh
        chmod 600 /home/"$APP_USER"/.ssh/authorized_keys
    fi
else
    echo "   User '$APP_USER' already exists — skipping."
fi

# ── Application directory ─────────────────────────────────────────────────────
echo "▶ Creating app directory $APP_DIR..."
mkdir -p "$APP_DIR"
chown "$APP_USER":"$APP_USER" "$APP_DIR"

# ── Firewall ──────────────────────────────────────────────────────────────────
echo "▶ Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh       # 22
ufw allow http      # 80
ufw allow https     # 443
ufw --force enable
ufw status verbose

# ── Fail2ban ──────────────────────────────────────────────────────────────────
echo "▶ Enabling fail2ban..."
systemctl enable --now fail2ban

# ── Automatic security updates ────────────────────────────────────────────────
echo "▶ Enabling unattended-upgrades..."
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# ── Swap (CX23 has 4 GB RAM — 2 GB swap is a sensible safety net) ────────────
if [[ ! -f /swapfile ]]; then
    echo "▶ Creating 2 GB swapfile..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
    echo "   Swapfile already exists — skipping."
fi

echo ""
echo "✅ Server bootstrap complete."
echo "   Next: log in as '$APP_USER' and follow DEPLOYMENT.md"
