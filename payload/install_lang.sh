#!/bin/sh
# install_lang.sh - Router-side language pack installer
# Uses overlay bind-mount on /data for squashfs persistence

PATCH_DIR="/data/lang_patch"
BACKUP_DIR="$PATCH_DIR/backup"
LMO_SRC="/usr/lib/lua/luci/i18n"
LUCI_DIR="/usr/lib/lua/luci"
VIEW_DIR="/usr/lib/lua/luci/view"
SHARE_DIR="/usr/share/xiaoqiang"

log() { echo "[lang_install] $*"; }
err() { log "ERROR: $*"; exit 1; }

# Phase 1: Backup original state
do_backup() {
    log "Backing up original state..."
    mkdir -p "$BACKUP_DIR"

    # Backup original LMO files
    [ -d "$LMO_SRC" ] && cp -a "$LMO_SRC" "$BACKUP_DIR/i18n_orig" 2>/dev/null

    # Save current language setting
    uci get luci.main.lang > "$BACKUP_DIR/orig_lang" 2>/dev/null

    # Save language list
    uci show luci.languages > "$BACKUP_DIR/orig_languages" 2>/dev/null

    # Backup critical view files for reference
    cp "$VIEW_DIR/web/inc/sysinfo.htm" "$BACKUP_DIR/" 2>/dev/null
    cp "$VIEW_DIR/web/inc/header.htm" "$BACKUP_DIR/" 2>/dev/null
}

# Phase 2: Set up overlay bind-mounts
setup_overlay() {
    log "Setting up overlay bind-mounts..."

    # Bind-mount /usr/lib/lua/luci (covers view/ + i18n/) to writable /data overlay
    if ! mount | grep -q " on $LUCI_DIR " ; then
        mkdir -p "$PATCH_DIR/luci"
        cp -a "$LUCI_DIR"/* "$PATCH_DIR/luci/"
        mount --bind "$PATCH_DIR/luci" "$LUCI_DIR"
        log "Bind-mounted $LUCI_DIR"
    fi

    # Bind-mount /usr/share/xiaoqiang if needed
    if ! mount | grep -q " on $SHARE_DIR" ; then
        mkdir -p "$PATCH_DIR/xiaoqiang"
        cp -a "$SHARE_DIR"/* "$PATCH_DIR/xiaoqiang/"
        mount --bind "$PATCH_DIR/xiaoqiang" "$SHARE_DIR"
        log "Bind-mounted $SHARE_DIR"
    fi
}

# Phase 3: Install LMO files
install_lmo() {
    log "Installing LMO files..."
    mkdir -p "$LMO_SRC"

    # Copy English LMO from payload
    if [ -f "$PATCH_DIR/base.en.lmo" ]; then
        cp "$PATCH_DIR/base.en.lmo" "$LMO_SRC/"
        log "Installed base.en.lmo"
    else
        err "base.en.lmo not found in $PATCH_DIR"
    fi
}

# Phase 4: Register English language in UCI
register_lang() {
    log "Registering English language..."

    # Check if 'en' is already registered
    if uci get luci.languages.en > /dev/null 2>&1; then
        log "English already registered"
    else
        uci set luci.languages.en='English'
        uci commit luci
        log "Registered luci.languages.en='English'"
    fi

    # Apply language setting
    uci set luci.main.lang='en'
    uci commit luci
}

# Phase 5: Persistence (survive reboots)
setup_persistence() {
    log "Setting up persistence..."

    PATCH_SCRIPT="$PATCH_DIR/lang_patch.sh"

    cat > "$PATCH_SCRIPT" << 'PATCH_EOF'
#!/bin/sh
# Auto-applied language patch (survives reboots)

PATCH_DIR="/data/lang_patch"
TARGET_DIR="/usr/lib/lua/luci"
MIRROR_DIR="$PATCH_DIR/luci"
LMO_DIR="/usr/lib/lua/luci/i18n"

mkdir -p "$MIRROR_DIR"

# Bind-mount entire luci dir (covers view/ + i18n/)
if ! mount | grep -q " on $TARGET_DIR " ; then
    # Only seed from squashfs if mirror is empty (first run)
    if [ ! -d "$MIRROR_DIR/view" ] || [ -z "$(ls -A "$MIRROR_DIR/view/" 2>/dev/null)" ]; then
        cp -a "$TARGET_DIR"/* "$MIRROR_DIR/" 2>/dev/null
    fi
    mount --bind "$MIRROR_DIR" "$TARGET_DIR"
fi

# Bind-mount xiaoqiang share
if ! mount | grep -q " on /usr/share/xiaoqiang" ; then
    if [ ! -d "$PATCH_DIR/xiaoqiang/cc" ] || [ -z "$(ls -A "$PATCH_DIR/xiaoqiang/" 2>/dev/null)" ]; then
        cp -a /usr/share/xiaoqiang/* "$PATCH_DIR/xiaoqiang/" 2>/dev/null
    fi
    mount --bind "$PATCH_DIR/xiaoqiang" /usr/share/xiaoqiang
fi

# Ensure LMO is in place
[ -f "$PATCH_DIR/base.en.lmo" ] && cp "$PATCH_DIR/base.en.lmo" "$LMO_DIR/"

# Re-apply language if changed
CURRENT=$(uci get luci.main.lang 2>/dev/null)
[ "$CURRENT" != "en" ] && uci set luci.main.lang='en' && uci commit luci

# Ensure en is registered
if ! uci get luci.languages.en > /dev/null 2>&1; then
    uci set luci.languages.en='English'
    uci commit luci
fi
PATCH_EOF

    chmod +x "$PATCH_SCRIPT"

    # Persistence via UCI firewall include
    uci set firewall.auto_lang_patch=include
    uci set firewall.auto_lang_patch.type='script'
    uci set firewall.auto_lang_patch.path="$PATCH_SCRIPT"
    uci set firewall.auto_lang_patch.enabled='1'
    uci commit firewall
    log "Added firewall include for auto-patch on boot"

    # Also add cron fallback
    grep -q "lang_patch.sh" /etc/crontabs/root 2>/dev/null || {
        echo "*/1 * * * * $PATCH_SCRIPT" >> /etc/crontabs/root
        /etc/init.d/cron restart 2>/dev/null
        log "Added cron fallback"
    }
}

# Main
log "=== Xiaomi BE3600 Language Install ==="
do_backup
setup_overlay
install_lmo
register_lang
setup_persistence

log "Installation complete. Language set to English."
log "Router web UI will reflect changes immediately."
