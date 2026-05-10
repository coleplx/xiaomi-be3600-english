#!/bin/bash
# deploy.sh - Build LMO and deploy to router via sshpass
# Usage: ./deploy.sh [--uninstall|--status|--upload-only]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env if present
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"

ROUTER_IP="${ROUTER_IP:-192.168.31.1}"
ROUTER_USER="${ROUTER_USER:-root}"
ROUTER_PASS="${ROUTER_PASS:-root}"

SSHPASS_CMD="sshpass -p '$ROUTER_PASS'"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa"

SSH_CMD="$SSHPASS_CMD ssh $SSH_OPTS ${ROUTER_USER}@${ROUTER_IP}"
SCP_CMD="$SSHPASS_CMD scp -O $SSH_OPTS"

log() { echo "[deploy] $*"; }

do_build() {
    log "Building LMO file..."
    python3 "$SCRIPT_DIR/scripts/build_lmo.py"
}

do_upload() {
    log "Uploading files to router..."

    # Create patch directory on router
    $SSH_CMD "mkdir -p /data/lang_patch/backup"

    # Upload LMO file
    $SCP_CMD "$SCRIPT_DIR/i18n/base.en.lmo" "${ROUTER_USER}@${ROUTER_IP}:/data/lang_patch/"

    # Upload install script
    $SCP_CMD "$SCRIPT_DIR/payload/install_lang.sh" "${ROUTER_USER}@${ROUTER_IP}:/data/lang_patch/"

    log "Upload complete."
}

do_install() {
    log "Running install script on router..."
    $SSH_CMD "chmod +x /data/lang_patch/install_lang.sh && sh /data/lang_patch/install_lang.sh"
}

do_uninstall() {
    log "Removing English language pack..."
    $SSH_CMD "
        # Remove bind mounts
        umount /usr/lib/lua/luci 2>/dev/null
        umount /usr/lib/lua/luci/view 2>/dev/null
        umount /usr/share/xiaoqiang 2>/dev/null

        # Restore language to Chinese
        uci set luci.main.lang='zh_cn'
        uci delete luci.languages.en 2>/dev/null
        uci commit luci

        # Remove firewall include
        uci delete firewall.auto_lang_patch 2>/dev/null
        uci commit firewall

        # Remove cron entry
        sed -i '/lang_patch.sh/d' /etc/crontabs/root 2>/dev/null
        /etc/init.d/cron restart 2>/dev/null

        # Remove LMO
        rm -f /usr/lib/lua/luci/i18n/base.en.lmo

        # Remove patch dir
        rm -rf /data/lang_patch

        echo 'Uninstall complete. Language restored to zh_cn.'
    "
}

do_status() {
    log "Checking router status..."
    $SSH_CMD "
        echo '--- Language ---'
        uci get luci.main.lang 2>/dev/null || echo 'not set'
        echo '--- Registered languages ---'
        uci show luci.languages 2>/dev/null
        echo '--- LMO files ---'
        ls -la /usr/lib/lua/luci/i18n/ 2>/dev/null
        echo '--- Bind mounts ---'
        mount | grep -E 'luci/view|xiaoqiang' 2>/dev/null || echo 'none'
        echo '--- Firewall include ---'
        uci show firewall.auto_lang_patch 2>/dev/null || echo 'none'
    "
}

case "${1:-}" in
    --uninstall)
        do_uninstall
        ;;
    --status)
        do_status
        ;;
    --upload-only)
        do_build
        do_upload
        ;;
    *)
        do_build
        do_upload
        do_install
        log "Done! Router UI should now be in English."
        log "Run './deploy.sh --status' to verify."
        log "Run './deploy.sh --uninstall' to revert."
        ;;
esac
