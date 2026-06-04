#!/bin/sh
# boot_setup.sh - Launch dashboard uhttpd on boot + VAP recovery
# Idempotent: safe to run multiple times (cron fallback every 2 min)

BASE="/data/dashboard"
WWW="$BASE/www"
CGI="$WWW/cgi-bin"
PIDFILE="/var/run/dashboard_uhttpd.pid"

log() { echo "[dashboard] $*"; }

apply_wifi_patches() {
    local patch_dir="$BASE/patched"
    [ -d "$patch_dir" ] || return 0

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

# Wait for wifi radios to be ready (poll up to 60s)
_wait_radios() {
    local max=60 waited=0
    while [ $waited -lt $max ]; do
        iw dev wifi0 info >/dev/null 2>&1 && iw dev wifi1 info >/dev/null 2>&1 && return 0
        sleep 2
        waited=$((waited + 2))
    done
    log "WARNING: radios not ready after ${max}s"
    return 1
}

# One-time VAP recovery after boot (radios just came up)
recover_vaps() {
    log "Starting VAP recovery..."

    _wait_radios || return

    local recovered=0 ok=0
    uci -X show wireless 2>/dev/null | grep '=wifi-iface' > /tmp/_vap_scan.tmp
    while IFS='=' read -r sec _; do
        local section=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$section" ] && continue

        local extra=$(uci -q get "wireless.${section}.extra_wifi" 2>/dev/null || echo "0")
        [ "$extra" != "1" ] && continue

        local disabled=$(uci -q get "wireless.${section}.disabled" 2>/dev/null || echo "0")
        [ "$disabled" = "1" ] && continue

        local ssid=$(uci -q get "wireless.${section}.ssid" 2>/dev/null || echo "")
        local ifname=$(uci -q get "wireless.${section}.ifname" 2>/dev/null || echo "")

        # Check if VAP is alive
        if [ -n "$ifname" ] && iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
            ok=$((ok + 1))
            continue
        fi

        # VAP missing or broken — recreate
        log "Recovering VAP $section (SSID: $ssid, ifname: ${ifname:-none})"
        sh /data/dashboard/apply_vap.sh create "$section" >/dev/null 2>&1
        # Brief sleep to let hostapd start
        sleep 3
        recovered=$((recovered + 1))
    done < /tmp/_vap_scan.tmp
    rm -f /tmp/_vap_scan.tmp

    log "VAP recovery done: $ok already up, $recovered recovered"
}

# Periodic health check (rate-limited, runs every 2 min via cron)
check_vaps() {
    local sentinel="/tmp/.vap_check_last"
    local now=$(date +%s 2>/dev/null || echo "0")
    local last=0
    [ -f "$sentinel" ] && last=$(cat "$sentinel" 2>/dev/null || echo "0")

    # Rate limit: 60s between checks
    [ $((now - last)) -lt 60 ] && [ "$now" -gt 0 ] && [ "$last" -gt 0 ] && return 0
    echo "$now" > "$sentinel"

    local fixed=0 ok=0

    uci -X show wireless 2>/dev/null | grep '=wifi-iface' > /tmp/_vap_check.tmp
    while IFS='=' read -r sec _; do
        local section=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$section" ] && continue

        local extra=$(uci -q get "wireless.${section}.extra_wifi" 2>/dev/null || echo "0")
        [ "$extra" != "1" ] && continue

        local disabled=$(uci -q get "wireless.${section}.disabled" 2>/dev/null || echo "0")
        [ "$disabled" = "1" ] && continue

        local ssid=$(uci -q get "wireless.${section}.ssid" 2>/dev/null || echo "")
        local ifname=$(uci -q get "wireless.${section}.ifname" 2>/dev/null || echo "")

        # Check 1: VAP interface exists with correct SSID
        if [ -n "$ifname" ] && iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
            # Check 2: our hostapd PID is alive
            local pidfile="/var/run/hostapd-${ifname}.pid"
            if [ -f "$pidfile" ]; then
                local pid=$(cat "$pidfile" 2>/dev/null)
                if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                    ok=$((ok + 1))
                    continue
                fi
            fi
            # PID file missing or stale but VAP is up — could be managed by global hostapd.
            # Check for Xiaomi WPS tags (global hostapd adds these) and re-apply to strip them
            local conf="/var/run/hostapd-${ifname}.conf"
            if [ -f "$conf" ] && grep -q "manufacturer=xiaomi" "$conf" 2>/dev/null; then
                log "Health check: stripping Xiaomi WPS from $ifname"
                sh /data/dashboard/apply_vap.sh update "$section" >/dev/null 2>&1
                sleep 2
                fixed=$((fixed + 1))
                continue
            fi
            ok=$((ok + 1))
            continue
        fi

        # VAP is down/broken — try update first (faster), then create
        log "Health check: fixing VAP $section (SSID: $ssid)"
        sh /data/dashboard/apply_vap.sh update "$section" >/dev/null 2>&1
        sleep 2
        fixed=$((fixed + 1))
    done < /tmp/_vap_check.tmp
    rm -f /tmp/_vap_check.tmp

    [ $fixed -gt 0 ] && log "Health check: $ok OK, $fixed fixed"
}

apply_wifi_patches
start_uhttpd
recover_vaps
check_vaps
