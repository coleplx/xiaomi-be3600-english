#!/bin/sh
# boot_setup.sh - Launch dashboard uhttpd on boot
# Idempotent: safe to run multiple times (cron fallback every 2 min)

BASE="/data/dashboard"
WWW="$BASE/www"
CGI="$WWW/cgi-bin"
PIDFILE="/var/run/dashboard_uhttpd.pid"

log() { echo "[dashboard] $*"; }

apply_wifi_patches() {
    local patch_dir="$BASE/patched"
    [ -d "$patch_dir" ] || return 0

    # Bind-mount patched wifi scripts over buggy Qualcomm originals.
    # hostapd.sh: added "local ssid device hwmode phy" to prevent variable leakage
    # qcawificfg80211.sh: neutered radio-index ifname "correction" that fights inverted naming
    for script in hostapd.sh qcawificfg80211.sh; do
        if [ -f "$patch_dir/$script" ] && ! mount | grep -q "/lib/wifi/$script"; then
            mount --bind "$patch_dir/$script" "/lib/wifi/$script" 2>/dev/null && \
                log "Patched $script"
        fi
    done
}

start_uhttpd() {
    if [ -f "$PIDFILE" ]; then
        oldpid=$(cat "$PIDFILE")
        if kill -0 "$oldpid" 2>/dev/null; then
            return 0
        fi
    fi

    stale=$(netstat -tlnp 2>/dev/null | grep ':8081' | awk '{print $NF}' | cut -d'/' -f1)
    [ -n "$stale" ] && kill "$stale" 2>/dev/null
    rm -f "$PIDFILE"

    [ -f "$CGI/api.cgi" ] && chmod +x "$CGI/api.cgi"

    uhttpd -p 8081 -h "$WWW" -x /cgi-bin -f &
    echo "$!" > "$PIDFILE"
    log "uhttpd started on port 8081"
}

apply_wifi_patches
start_uhttpd
