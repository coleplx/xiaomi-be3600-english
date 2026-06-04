#!/bin/sh
# apply_vap.sh - Lightweight VAP management (no wifi lock)
# Generates hostapd config from scratch (no template dependency)
# Usage: apply_vap.sh create|delete|update <uci_section> [ifname_override]

BASE="/data/extra_wifi"
ACTION="$1"
SECTION="$2"
EXTRA_IFNAME="$3"

[ -z "$SECTION" ] && { echo "Usage: $0 create|delete|update <section>"; exit 1; }

log() { echo "[apply_vap] $*"; }
g() { uci -q get "wireless.${SECTION}.${1}" 2>/dev/null; }

# Write result so callers (api.cgi) can poll for completion
write_result() {
    echo "$1" > "/tmp/apply_vap_result.${SECTION}"
}
cleanup_result() {
    rm -f "/tmp/apply_vap_result.${SECTION}"
}

# Check whether another (non-disabled) UCI section already claims this ifname
ifname_collision() {
    local ifname="$1"
    uci -X show wireless 2>/dev/null | grep '=wifi-iface' | while IFS='=' read -r sec _; do
        local sname=$(echo "$sec" | cut -d'.' -f2)
        [ "$sname" = "$SECTION" ] && continue
        local d=$(uci -q get "wireless.${sname}.disabled" 2>/dev/null || echo "0")
        [ "$d" = "1" ] && continue
        local n=$(uci -q get "wireless.${sname}.ifname" 2>/dev/null || echo "")
        [ "$n" = "$ifname" ] && { echo "1"; return 0; }
    done
    echo "0"
}

gen_config() {
    local ifname="$1" radio="$2"
    local ssid enc key htmode net_if bridge_if
    ssid=$(g ssid)
    enc=$(g encryption)
    key=$(g key)
    htmode=$(g htmode)
    net_if=$(g network)
    [ -z "$net_if" ] && net_if="lan"

    if [ "$net_if" = "lan" ]; then
        bridge_if="br-lan"
    else
        bridge_if="br-${net_if}"
        brctl addbr "$bridge_if" 2>/dev/null
        local vlan_num="${net_if#vlan_}"
        ip link add link eth1 name "eth1.${vlan_num}" type vlan id "${vlan_num}" 2>/dev/null
        brctl addif "$bridge_if" "eth1.${vlan_num}" 2>/dev/null
        ifconfig "eth1.${vlan_num}" up 2>/dev/null
        ifconfig "$bridge_if" up 2>/dev/null
    fi

    local conf="/var/run/hostapd-${ifname}.conf"

    cat > "$conf" << EOF
driver=nl80211
interface=${ifname}
logger_syslog=127
logger_syslog_level=2
logger_stdout=127
logger_stdout_level=2
wmm_enabled=1
dtim_period=1
ignore_broadcast_ssid=0
ctrl_interface=/var/run/hostapd-${radio}
send_probe_response=0
noauth_pasn_activated=1
owe_ptk_workaround=1
ssid=${ssid}
bridge=${bridge_if}
EOF

    if [ "$radio" = "wifi1" ]; then
        cat >> "$conf" << EOF
hw_mode=a
channel=auto
ieee80211n=1
ieee80211ac=1
ieee80211ax=1
ieee80211be=1
eht_oper_chwidth=1
eht_oper_centr_freq_seg0_idx=-6
puncture_bitmap= 0xffff
ht_capab=[LDPC][TX-STBC][RX-STBC-1][MAX-AMSDU-7935][DSSS_CCK-40] [SHORT-GI-40]
vht_capab=[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][RX-STBC1][SU-BEAMFORMER][SOUNDING-DIMENSION-2][SU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7][MU-BEAMFORMER][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN]
EOF
    else
        cat >> "$conf" << EOF
hw_mode=g
channel=auto
ieee80211n=1
ieee80211ac=1
ieee80211ax=1
ieee80211be=1
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

cleanup_stale_pid() {
    local ifname="$1"
    local pidfile="/var/run/hostapd-${ifname}.pid"
    if [ -f "$pidfile" ]; then
        local stale_pid=$(cat "$pidfile" 2>/dev/null)
        if [ -n "$stale_pid" ] && ! kill -0 "$stale_pid" 2>/dev/null; then
            rm -f "$pidfile"
        fi
    fi
}

try_create_vap() {
    local ifname="$1" radio="$2" ssid="$3"

    # Check for UCI ifname collision (skip disabled sections)
    if [ "$(ifname_collision "$ifname")" = "1" ]; then
        log "SKIP $ifname: collision with another active UCI section"
        return 1
    fi

    rm -f "/var/run/hostapd-${radio}/${ifname}"

    iw dev "$radio" interface add "$ifname" type __ap 2>/dev/null || return 1

    local conf=$(gen_config "$ifname" "$radio")
    [ -z "$conf" ] && { iw dev "$ifname" del 2>/dev/null; return 1; }

    cleanup_stale_pid "$ifname"
    local pidfile="/var/run/hostapd-${ifname}.pid"
    hostapd -B -P "$pidfile" "$conf" 2>/dev/null
    sleep 2

    if iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
        return 0
    fi

    # Failed — clean up
    kill $(cat "$pidfile" 2>/dev/null) 2>/dev/null
    sleep 1
    iw dev "$ifname" del 2>/dev/null
    rm -f "$conf" "$pidfile" "/var/run/hostapd-${ifname}.lock"
    return 1
}

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
    esac

    local suffix
    for suffix in 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
        local ifname="wl${radionum}${suffix:1}"

        iw dev "$ifname" info >/dev/null 2>&1 && continue

        log "Trying VAP $ifname on $radio (SSID: $ssid)"
        if try_create_vap "$ifname" "$radio" "$ssid"; then
            uci set "wireless.${SECTION}.ifname=${ifname}"
            uci commit wireless
            log "VAP $ifname started OK"
            write_result "OK $ifname"
            return 0
        fi
        log "VAP $ifname failed, trying next..."
        sleep 1
    done

    log "ERROR: all suffixes 10-30 failed for $radio"
    write_result "FAIL all suffixes exhausted"
    exit 1
}

do_delete() {
    local ifname="${EXTRA_IFNAME:-$(g ifname)}"
    [ -z "$ifname" ] && { log "SKIP: no ifname for $SECTION"; write_result "OK"; exit 0; }

    log "Deleting VAP $ifname (SSID: $(g ssid))"

    local pidfile="/var/run/hostapd-${ifname}.pid"
    [ -f "$pidfile" ] && kill $(cat "$pidfile") 2>/dev/null

    sleep 1
    brctl delif br-lan "$ifname" 2>/dev/null
    brctl delif "br-vlan_"* "$ifname" 2>/dev/null
    iw dev "$ifname" del 2>/dev/null

    rm -f "/var/run/hostapd-${ifname}.conf" \
          "/var/run/hostapd-${ifname}.pid" \
          "/var/run/hostapd-${ifname}.lock" \
          "/var/run/hostapd-wifi0/${ifname}" \
          "/var/run/hostapd-wifi1/${ifname}"

    log "VAP $ifname deleted"
    write_result "OK"
}

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

    # Kill existing hostapd for this VAP
    local pidfile="/var/run/hostapd-${ifname}.pid"
    if [ -f "$pidfile" ]; then
        kill $(cat "$pidfile") 2>/dev/null
        sleep 1
    fi

    # Regenerate config and restart
    local conf=$(gen_config "$ifname" "$radio")
    [ -z "$conf" ] && { write_result "FAIL config gen"; exit 1; }

    cleanup_stale_pid "$ifname"
    hostapd -B -P "$pidfile" "$conf" 2>/dev/null
    sleep 2

    if iw dev "$ifname" info 2>/dev/null | grep -q "ssid ${ssid}"; then
        log "VAP $ifname updated OK"
        write_result "OK $ifname"
    else
        log "ERROR: update failed for $ifname, trying create"
        do_create
    fi
}

cleanup_result

case "$ACTION" in
    create) do_create ;;
    delete) do_delete ;;
    update)  do_update ;;
    *) echo "Unknown action: $ACTION"; write_result "FAIL unknown action"; exit 1 ;;
esac
