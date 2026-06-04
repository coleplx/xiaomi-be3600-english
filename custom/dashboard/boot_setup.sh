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

# Clean up zombie interfaces (wlXX with no SSID and no active UCI entry)
cleanup_zombies() {
    local cleaned=0
    for iface in /sys/class/net/wl*/address; do
        [ -f "$iface" ] || continue
        local iname="${iface%/address}"
        iname="${iname##*/}"

        # Skip factory interfaces
        case "$iname" in wl[0-9]) continue ;; esac

        # Check if any UCI section references this ifname
        local has_uci=0
        uci -X show wireless 2>/dev/null | grep "ifname='${iname}'" >/dev/null 2>&1 && has_uci=1

        # If no UCI and no SSID, it's a zombie
        if [ "$has_uci" = "0" ]; then
            local ssid=$(iw dev "$iname" info 2>/dev/null | grep ssid | awk '{print $2}')
            if [ -z "$ssid" ]; then
                log "Cleaning zombie: $iname"
                iw dev "$iname" del 2>/dev/null
                rm -f "/var/run/hostapd-${iname}".*
                cleaned=$((cleaned + 1))
            fi
        fi
    done
    [ $cleaned -gt 0 ] && log "Cleaned $cleaned zombie interfaces"
}

# Strip Xiaomi WPS from a VAP config managed by the global hostapd
# The global hostapd injects manufacturer=xiaomi etc into every auto-generated config.
# We strip those lines and restart the VAP with our clean config.
strip_wps() {
    local ifname="$1" section="$2"
    local conf="/var/run/hostapd-${ifname}.conf"
    [ -f "$conf" ] || return 1

    # Only strip if Xiaomi WPS is present
    grep -q "manufacturer=xiaomi" "$conf" 2>/dev/null || return 0

    log "Stripping Xiaomi WPS from $ifname"
    # Remove Xiaomi-specific WPS lines
    sed -i '/^manufacturer=/d; /^device_name=/d; /^model_name=/d; /^serial_number=/d; /^uuid=/d; /^wps_state=/d; /^pbc_in_m1=/d; /^eap_server=/d; /^wps_independent=/d; /^wps_rf_bands=/d; /^device_type=/d; /^config_methods=/d; /^ap_setup_locked=/d; /^wps_cred_add_sae=/d' "$conf" 2>/dev/null

    # Restart the VAP with stripped config
    sh /data/dashboard/apply_vap.sh update "$section" >/dev/null 2>&1
    return 0
}

# Reapply unique MAC addresses on VLAN subinterfaces (lost at reboot)
fix_vlan_macs() {
    local fixed=0
    uci -X show network 2>/dev/null | grep '=interface' | while IFS='=' read -r sec _; do
        local iname=$(echo "$sec" | cut -d'.' -f2)
        local uci_mac=$(uci -q get "network.${iname}.macaddr" 2>/dev/null || echo "")
        local uci_ifname=$(uci -q get "network.${iname}.ifname" 2>/dev/null || echo "")
        [ -z "$uci_mac" ] && continue

        # Only fix VLAN subinterfaces (eth1.N)
        local vif=$(echo "$uci_ifname" | awk '{print $1}')
        case "$vif" in
            eth1.*) ;;
            *) continue ;;
        esac

        local current_mac=$(cat /sys/class/net/${vif}/address 2>/dev/null)
        if [ "$current_mac" != "$uci_mac" ]; then
            log "Fixing MAC on $vif: $current_mac -> $uci_mac"
            ip link set "$vif" address "$uci_mac" 2>/dev/null
            if [ -d "/sys/class/net/br-${iname}" ]; then
                ip link set "br-${iname}" address "$uci_mac" 2>/dev/null
            fi
            fixed=$((fixed + 1))
        fi
    done
    [ $fixed -gt 0 ] && log "Fixed $fixed VLAN MAC addresses"
}

# Health check: ensure all extra_wifi VAPs are running and WPS-free
# The global hostapd recreates VAPs at boot with Xiaomi WPS in the config.
# If our per-VAP hostapd is not running (no PID file), strip WPS and restart.
check_vaps() {
    local sentinel="/tmp/.vap_check_last"
    local now=$(date +%s 2>/dev/null || echo "0")
    local last=0
    [ -f "$sentinel" ] && last=$(cat "$sentinel" 2>/dev/null || echo "0")

    # Rate limit: 60s between checks
    [ $((now - last)) -lt 60 ] && [ "$now" -gt 0 ] && [ "$last" -gt 0 ] && return 0
    echo "$now" > "$sentinel"

    local fixed=0 ok=0

    # First pass: strip WPS from any global hostapd-managed config (no our PID)
    for conf in /var/run/hostapd-wl*.conf; do
        [ -f "$conf" ] || continue
        local ifname=$(grep '^interface=' "$conf" | cut -d= -f2)
        [ -z "$ifname" ] && continue

        # Skip if this VAP has our hostapd PID (apply_vap.sh managed)
        if [ -f "/var/run/hostapd-${ifname}.pid" ]; then
            local pid=$(cat "/var/run/hostapd-${ifname}.pid" 2>/dev/null)
            [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && continue
        fi

        # Check if this VAP belongs to an extra_wifi section
        local section=""
        uci -X show wireless 2>/dev/null | grep '=wifi-iface' > /tmp/_vap_owner.tmp
        while IFS='=' read -r sec _; do
            local sname=$(echo "$sec" | cut -d'.' -f2)
            [ -z "$sname" ] && continue
            local extra=$(uci -q get "wireless.${sname}.extra_wifi" 2>/dev/null || echo "0")
            [ "$extra" != "1" ] && continue
            local uci_if=$(uci -q get "wireless.${sname}.ifname" 2>/dev/null || echo "")
            [ "$uci_if" = "$ifname" ] && { section="$sname"; break; }
        done < /tmp/_vap_owner.tmp
        rm -f /tmp/_vap_owner.tmp

        [ -z "$section" ] && continue  # not our VAP

        # Global hostapd owns this VAP (no our PID). Verify it's actually broadcasting.
        local ssid=$(uci -q get "wireless.${section}.ssid" 2>/dev/null || echo "")
        local alive=0
        [ -n "$ssid" ] && iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}" && alive=1

        if [ "$alive" = "0" ]; then
            log "Restarting VAP $ifname (SSID: $ssid) — global hostapd didn't start it"
            sh /data/dashboard/apply_vap.sh update "$section" >/dev/null 2>&1
            sleep 2
            fixed=$((fixed + 1))
        elif grep -q "manufacturer=xiaomi" "$conf" 2>/dev/null; then
            log "Stripping Xiaomi WPS from $ifname (SSID: $ssid)"
            sh /data/dashboard/apply_vap.sh update "$section" >/dev/null 2>&1
            sleep 2
            fixed=$((fixed + 1))
        else
            ok=$((ok + 1))
        fi
    done

    # Second pass: find extra_wifi sections whose VAP is missing
    uci -X show wireless 2>/dev/null | grep '=wifi-iface' > /tmp/_vap_missing.tmp
    while IFS='=' read -r sec _; do
        local section=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$section" ] && continue

        local extra=$(uci -q get "wireless.${section}.extra_wifi" 2>/dev/null || echo "0")
        [ "$extra" != "1" ] && continue

        local disabled=$(uci -q get "wireless.${section}.disabled" 2>/dev/null || echo "0")
        [ "$disabled" = "1" ] && continue

        local ssid=$(uci -q get "wireless.${section}.ssid" 2>/dev/null || echo "")
        local ifname=$(uci -q get "wireless.${section}.ifname" 2>/dev/null || echo "")

        if [ -z "$ifname" ] || ! iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
            log "VAP missing for $section (SSID: $ssid, ifname: ${ifname:-none})"
            sh /data/dashboard/apply_vap.sh create "$section" >/dev/null 2>&1
            sleep 3
            fixed=$((fixed + 1))
        fi
    done < /tmp/_vap_missing.tmp
    rm -f /tmp/_vap_missing.tmp

    # Clean up orphan VAPs: wlXX interfaces with no UCI owner that have an SSID
    # These are duplicates created by the global hostapd
    for iface_path in /sys/class/net/wl*/address; do
        [ -f "$iface_path" ] || continue
        local iname="${iface_path%/address}"; iname="${iname##*/}"
        case "$iname" in wl[0-9]) continue ;; esac  # skip factory

        local has_uci=0
        uci -X show wireless 2>/dev/null | grep -q "ifname='${iname}'" && has_uci=1
        [ "$has_uci" = "1" ] && continue

        # Check if it has an active hostapd
        if [ -f "/var/run/hostapd-${iname}.pid" ]; then
            local pid=$(cat "/var/run/hostapd-${iname}.pid" 2>/dev/null)
            [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && {
                log "Removing orphan VAP $iname"
                kill "$pid" 2>/dev/null
            }
        fi
        sleep 1
        iw dev "$iname" del 2>/dev/null
        rm -f "/var/run/hostapd-${iname}".*
    done

    [ $fixed -gt 0 ] && log "Health check: $ok OK, $fixed fixed"
    [ $fixed -eq 0 ] && log "Health check: all $ok VAPs healthy"
}

apply_wifi_patches
start_uhttpd
_wait_radios || true
cleanup_zombies
fix_vlan_macs
check_vaps
