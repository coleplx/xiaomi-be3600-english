#!/bin/sh
# apply_vap.sh - Lightweight VAP management (no wifi lock)
# Generates hostapd config from scratch (no template dependency)
# Usage: apply_vap.sh create|delete|update <uci_section> [ifname_override]

ACTION="$1"
SECTION="$2"
EXTRA_IFNAME="$3"

[ -z "$SECTION" ] && { echo "Usage: $0 create|delete|update <section>"; exit 1; }

log() { echo "[apply_vap] $(date +%H:%M:%S) $*"; }
g() { uci -q get "wireless.${SECTION}.${1}" 2>/dev/null; }

RESULT_FILE="/tmp/apply_vap_result.${SECTION}"
write_result() { echo "$1" > "$RESULT_FILE"; }

# ── Validate bridge exists ──
bridge_exists() {
    [ -d "/sys/class/net/$1/bridge" ] && return 0
    return 1
}

# ── ifname collision: check UCI (disabled sections excluded) ──
ifname_collision() {
    local ifname="$1"
    local result=0
    uci -X show wireless 2>/dev/null | grep '=wifi-iface' | while IFS='=' read -r sec _; do
        local sname=$(echo "$sec" | cut -d'.' -f2)
        [ "$sname" = "$SECTION" ] && continue
        local d=$(uci -q get "wireless.${sname}.disabled" 2>/dev/null || echo "0")
        [ "$d" = "1" ] && continue
        local n=$(uci -q get "wireless.${sname}.ifname" 2>/dev/null || echo "")
        [ "$n" = "$ifname" ] && echo "1" && return 0
    done
    echo "0"
}

# ── Resolve bridge for a given network name ──
resolve_bridge() {
    local net_if="$1"
    if [ "$net_if" = "lan" ]; then
        echo "br-lan"
    elif bridge_exists "br-${net_if}"; then
        echo "br-${net_if}"
    else
        echo ""
    fi
}

# ── Generate hostapd config ──
gen_config() {
    local ifname="$1" radio="$2"
    local ssid enc key bridge_if
    ssid=$(g ssid)
    enc=$(g encryption)
    key=$(g key)
    local net_if=$(g network)
    [ -z "$net_if" ] && net_if="lan"

    bridge_if=$(resolve_bridge "$net_if")
    if [ -z "$bridge_if" ]; then
        # Bridge doesn't exist yet — hostapd will auto-create it.
        # Warn but proceed; the VLAN subinterface (eth1.N) must be added
        # separately for traffic to flow.
        bridge_if="br-${net_if}"
        log "WARNING: bridge ${bridge_if} does not exist, hostapd will auto-create"
    fi

    local conf="/var/run/hostapd-${ifname}.conf"

    cat > "$conf" << EOF
driver=nl80211
interface=${ifname}
ctrl_interface=/var/run/hostapd-${radio}
ssid=${ssid}
bridge=${bridge_if}
hw_mode=a
channel=auto
ieee80211ac=1
ieee80211n=1
ieee80211ax=1
ieee80211be=1
wmm_enabled=1
dtim_period=1
ignore_broadcast_ssid=0
send_probe_response=0
noauth_pasn_activated=1
owe_ptk_workaround=1
EOF

    if [ "$radio" = "wifi1" ]; then
        cat >> "$conf" << EOF
eht_oper_chwidth=1
eht_oper_centr_freq_seg0_idx=-6
puncture_bitmap= 0xffff
ht_capab=[LDPC][TX-STBC][RX-STBC-1][MAX-AMSDU-7935][DSSS_CCK-40] [SHORT-GI-40]
vht_capab=[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][RX-STBC1][SU-BEAMFORMER][SOUNDING-DIMENSION-2][SU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7][MU-BEAMFORMER][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN]
EOF
    else
        cat >> "$conf" << EOF
hw_mode=g
eht_oper_chwidth=0
eht_oper_centr_freq_seg0_idx=-6
puncture_bitmap= 0xffff
ht_capab=[LDPC][TX-STBC][RX-STBC-1][MAX-AMSDU-7935][DSSS_CCK-40][HT40+] [SHORT-GI-40]
vht_capab=[MAX-MPDU-11454][RXLDPC][TX-STBC-2BY1][RX-STBC1][SU-BEAMFORMER][SOUNDING-DIMENSION-2][SU-BEAMFORMEE][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7][MU-BEAMFORMER][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN]
EOF
    fi

    if [ "$enc" = "none" ]; then
        echo "auth_algs=1" >> "$conf"
    else
        cat >> "$conf" << EOF
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
wpa_group_rekey=0
EOF
        [ -n "$key" ] && echo "wpa_passphrase=${key}" >> "$conf"
    fi

    echo "$conf"
}

# ── Verify a hostapd process is actually alive at the given PID ──
hostapd_alive() {
    local pidfile="$1"
    local pid
    [ -f "$pidfile" ] || return 1
    pid=$(cat "$pidfile" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && return 0
    return 1
}

# ── Cleanup after failed VAP creation ──
vap_cleanup() {
    local ifname="$1" conf="$2" pidfile="$3"
    local pid
    pid=$(cat "$pidfile" 2>/dev/null)
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
    sleep 1
    iw dev "$ifname" del 2>/dev/null
    rm -f "$conf" "$pidfile" "/var/run/hostapd-${ifname}.lock"
}

# ── Try to create VAP, with retry ──
try_create_vap() {
    local ifname="$1" radio="$2" ssid="$3"

    if [ "$(ifname_collision "$ifname")" = "1" ]; then
        log "SKIP $ifname: UCI collision"
        return 1
    fi

    rm -f "/var/run/hostapd-${radio}/${ifname}"

    if ! iw dev "$radio" interface add "$ifname" type __ap 2>/dev/null; then
        log "FAIL $ifname: iw interface add failed (already exists?)"
        return 1
    fi

    local conf pidfile errlog
    conf=$(gen_config "$ifname" "$radio") || {
        log "FAIL $ifname: config generation failed (no bridge?)"
        iw dev "$ifname" del 2>/dev/null
        return 1
    }
    pidfile="/var/run/hostapd-${ifname}.pid"
    errlog="/tmp/hostapd-${ifname}.err"

    # Retry up to 2 times
    for attempt in 1 2; do
        hostapd -B -P "$pidfile" "$conf" >/dev/null 2>"$errlog"
        local waited=0
        while [ $waited -lt 5 ]; do
            sleep 1
            waited=$((waited + 1))
            if hostapd_alive "$pidfile"; then
                if iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
                    rm -f "$errlog"
                    log "VAP $ifname started (attempt $attempt, ${waited}s)"
                    return 0
                fi
            fi
        done

        if [ "$attempt" = "1" ]; then
            log "RETRY $ifname: first attempt failed, cleaning up..."
            # Read errors for debugging
            [ -s "$errlog" ] && log "hostapd stderr: $(tr '\n' ' ' < "$errlog")"
            vap_cleanup "$ifname" "$conf" "$pidfile"
            # Re-create the interface
            if ! iw dev "$radio" interface add "$ifname" type __ap 2>/dev/null; then
                log "FAIL $ifname: cannot re-create interface"
                rm -f "$errlog"
                return 1
            fi
            conf=$(gen_config "$ifname" "$radio") || { iw dev "$ifname" del 2>/dev/null; rm -f "$errlog"; return 1; }
            pidfile="/var/run/hostapd-${ifname}.pid"
        fi
    done

    log "FAIL $ifname: hostapd did not start after 2 attempts"
    [ -s "$errlog" ] && log "hostapd errors: $(tr '\n' ' ' < "$errlog")"
    vap_cleanup "$ifname" "$conf" "$pidfile"
    rm -f "$errlog"
    return 1
}

# ── CREATE ──
do_create() {
    local radio=$(g device)
    [ -z "$radio" ] && { log "ERROR: no device"; write_result "FAIL no device"; exit 1; }

    local ssid=$(g ssid)
    local disabled=$(g disabled)
    [ "$disabled" = "1" ] && { log "SKIP: ${SECTION} is disabled"; write_result "SKIP disabled"; exit 0; }
    [ -z "$ssid" ] && { log "ERROR: no ssid"; write_result "FAIL no ssid"; exit 1; }

    local radionum
    case "$radio" in
        wifi0) radionum=1 ;;
        wifi1) radionum=0 ;;
        *)     log "ERROR: unknown radio $radio"; write_result "FAIL unknown radio"; exit 1 ;;
    esac

    local suffix
    for suffix in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
        local ifname="wl${radionum}${suffix:1}"

        iw dev "$ifname" info >/dev/null 2>&1 && continue

        log "Trying $ifname on $radio (SSID: $ssid)"
        if try_create_vap "$ifname" "$radio" "$ssid"; then
            uci set "wireless.${SECTION}.ifname=${ifname}"
            uci commit wireless
            write_result "OK $ifname"
            return 0
        fi
        sleep 1
    done

    log "ERROR: all suffixes exhausted for $radio"
    write_result "FAIL all suffixes exhausted"
    exit 1
}

# ── DELETE ──
do_delete() {
    local ifname="${EXTRA_IFNAME:-$(g ifname)}"
    [ -z "$ifname" ] && { log "SKIP: no ifname for $SECTION"; write_result "OK"; exit 0; }

    log "Deleting VAP $ifname (SSID: $(g ssid))"

    local pidfile="/var/run/hostapd-${ifname}.pid"
    local pid
    pid=$(cat "$pidfile" 2>/dev/null)
    # Kill only OUR hostapd (per-VAP), not the global one
    if [ -n "$pid" ] && grep -q "hostapd-${ifname}.conf" /proc/${pid}/cmdline 2>/dev/null; then
        kill "$pid" 2>/dev/null
        sleep 1
    fi

    # iw dev del works even if hostapd is still running
    iw dev "$ifname" del 2>/dev/null

    rm -f "/var/run/hostapd-${ifname}.conf" \
          "/var/run/hostapd-${ifname}.pid" \
          "/var/run/hostapd-${ifname}.lock" \
          "/var/run/hostapd-wifi0/${ifname}" \
          "/var/run/hostapd-wifi1/${ifname}" \
          "/tmp/hostapd-${ifname}.err"

    log "VAP $ifname deleted"
    write_result "OK"
}

# ── UPDATE ──
do_update() {
    local radio=$(g device)
    local ssid=$(g ssid)
    local disabled=$(g disabled)
    [ "$disabled" = "1" ] && { log "SKIP: ${SECTION} is disabled"; write_result "SKIP disabled"; exit 0; }
    [ -z "$radio" ] && { log "ERROR: no device"; write_result "FAIL no device"; exit 1; }

    local ifname="${EXTRA_IFNAME:-$(g ifname)}"

    # If ifname is empty or interface doesn't exist, fall back to create
    if [ -z "$ifname" ] || ! iw dev "$ifname" info >/dev/null 2>&1; then
        log "VAP $ifname missing, falling back to create"
        do_create
        return
    fi

    # Kill existing per-VAP hostapd for this VAP
    local pidfile="/var/run/hostapd-${ifname}.pid"
    local pid
    pid=$(cat "$pidfile" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        sleep 1
    fi

    # Regenerate config and restart
    local conf errlog
    conf=$(gen_config "$ifname" "$radio") || {
        log "FAIL: config generation failed"
        write_result "FAIL config gen"
        exit 1
    }
    pidfile="/var/run/hostapd-${ifname}.pid"
    errlog="/tmp/hostapd-${ifname}.err"

    hostapd -B -P "$pidfile" "$conf" >/dev/null 2>"$errlog"
    sleep 2

    if hostapd_alive "$pidfile" && iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
        rm -f "$errlog"
        log "VAP $ifname updated OK"
        write_result "OK $ifname"
    else
        [ -s "$errlog" ] && log "hostapd errors: $(tr '\n' ' ' < "$errlog")"
        rm -f "$errlog"
        log "ERROR: update failed for $ifname, trying create"
        iw dev "$ifname" del 2>/dev/null
        rm -f "$conf" "$pidfile"
        do_create
    fi
}

rm -f "$RESULT_FILE"

case "$ACTION" in
    create) do_create ;;
    delete) do_delete ;;
    update)  do_update ;;
    *) echo "Unknown action: $ACTION"; write_result "FAIL unknown action"; exit 1 ;;
esac
