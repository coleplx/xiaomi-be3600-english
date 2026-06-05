#!/bin/bash
# deploy.sh - Upload and activate dashboard custom page
# Usage: ./deploy.sh [--uninstall]
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROUTER_IP="${ROUTER_IP:-192.168.10.209}"
ROUTER_USER="${ROUTER_USER:-root}"
ROUTER_PASS="${ROUTER_PASS:-root}"

# Load .env from project root if available
[ -f "$SCRIPT_DIR/../../.env" ] && source "$SCRIPT_DIR/../../.env"

SSH_CMD="sshpass -p $ROUTER_PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa ${ROUTER_USER}@${ROUTER_IP}"
SCP_CMD="sshpass -p $ROUTER_PASS scp -O -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa"

REMOTE_BASE="/data/dashboard"

log() { echo "[dashboard] $*"; }

do_deploy() {
    log "Uploading files to ${ROUTER_IP}..."

    $SSH_CMD "mkdir -p $REMOTE_BASE/www/cgi-bin"

    $SCP_CMD "$SCRIPT_DIR/index.html"    "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/www/"
    $SCP_CMD "$SCRIPT_DIR/api.cgi"       "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/www/cgi-bin/"
    $SCP_CMD "$SCRIPT_DIR/boot_setup.sh" "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/"
    $SCP_CMD "$SCRIPT_DIR/disable_xiaomi.sh" "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/"

    # Copy apply_vap.sh from extra_wifi for Wireless tab VAP operations
    [ -f "$SCRIPT_DIR/../extra_wifi/apply_vap.sh" ] && $SCP_CMD "$SCRIPT_DIR/../extra_wifi/apply_vap.sh" "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/"

    # Copy patched wifi scripts (fixes Qualcomm variable-leakage & ifname-corruption bugs)
    $SSH_CMD "mkdir -p $REMOTE_BASE/patched"
    [ -f "$SCRIPT_DIR/patched/hostapd.sh" ] && $SCP_CMD "$SCRIPT_DIR/patched/hostapd.sh" "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/patched/"
    [ -f "$SCRIPT_DIR/patched/qcawificfg80211.sh" ] && $SCP_CMD "$SCRIPT_DIR/patched/qcawificfg80211.sh" "${ROUTER_USER}@${ROUTER_IP}:${REMOTE_BASE}/patched/"

    $SSH_CMD "chmod +x $REMOTE_BASE/www/cgi-bin/api.cgi $REMOTE_BASE/boot_setup.sh $REMOTE_BASE/disable_xiaomi.sh $REMOTE_BASE/apply_vap.sh 2>/dev/null"

    # Setup authentication
    setup_auth

    log "Starting uhttpd on port 8081..."
    $SSH_CMD "sh $REMOTE_BASE/boot_setup.sh"

    log "Stopping Xiaomi background services..."
    $SSH_CMD "sh $REMOTE_BASE/disable_xiaomi.sh"

    setup_persistence || log "WARNING: persistence setup had issues (check manually)"

    log ""
    log "============================================"
    log "Dashboard available at: http://${ROUTER_IP}:8081/"
    log "Login: admin / ${ROUTER_PASS}"
    log "Survives reboots: YES"
    log "============================================"
}

setup_auth() {
    log "Configuring authentication..."
    $SSH_CMD "
        echo '${ROUTER_PASS}' > ${REMOTE_BASE}/.passwd
        chmod 600 ${REMOTE_BASE}/.passwd
    "
    log "Auth configured (user: admin)"
}

setup_persistence() {
    log "Setting up boot persistence..."

    # UCI firewall include (runs on every boot)
    $SSH_CMD "
        uci get firewall.dashboard > /dev/null 2>&1 || {
            uci set firewall.dashboard=include
            uci set firewall.dashboard.type='script'
            uci set firewall.dashboard.path='${REMOTE_BASE}/boot_setup.sh'
            uci set firewall.dashboard.enabled='1'
            uci commit firewall
        }
    "

    # Cron: disable_xiaomi.sh runs every 3 min (firewall include runs too early
    # at boot, before services start — cron catches them after they're up)
    $SSH_CMD "
        if ! grep -q 'dashboard/disable_xiaomi' /etc/crontabs/root 2>/dev/null; then
            echo '*/3 * * * * ${REMOTE_BASE}/disable_xiaomi.sh' >> /etc/crontabs/root
            /etc/init.d/cron restart 2>/dev/null || true
        fi
    "

    # Cron fallback: boot_setup.sh every 2 min (keeps uhttpd alive)
    $SSH_CMD "
        if ! grep -q 'dashboard/boot_setup' /etc/crontabs/root 2>/dev/null; then
            echo '*/2 * * * * ${REMOTE_BASE}/boot_setup.sh' >> /etc/crontabs/root
            /etc/init.d/cron restart 2>/dev/null || true
        fi
    "

    log "Persistence configured."
}

do_uninstall() {
    log "Stopping uhttpd..."
    $SSH_CMD "
        kill \$(cat /var/run/dashboard_uhttpd.pid 2>/dev/null) 2>/dev/null
        rm -f /var/run/dashboard_uhttpd.pid
    "

    log "Removing firewall include..."
    $SSH_CMD "
        uci delete firewall.dashboard 2>/dev/null
        uci delete firewall.disable_xiaomi 2>/dev/null
        uci commit firewall
    "

    log "Removing cron entry..."
    $SSH_CMD "
        sed -i '/dashboard\/boot_setup/d' /etc/crontabs/root 2>/dev/null
        /etc/init.d/cron restart 2>/dev/null || true
    "

    log "Removing files..."
    $SSH_CMD "rm -rf $REMOTE_BASE"

    log "Uninstall complete."
}

case "${1:-}" in
    --uninstall) do_uninstall ;;
    *) do_deploy ;;
esac
