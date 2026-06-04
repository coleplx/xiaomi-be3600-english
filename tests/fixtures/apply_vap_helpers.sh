# Extracted from apply_vap.sh — logic functions.
# These need stubs for: uci, /sys/class/net

resolve_bridge() {
    local net_if="$1"
    # Tests can override NET_BASE to mock /sys/class/net
    local base="${NET_BASE:-/sys/class/net}"
    if [ "$net_if" = "lan" ]; then
        echo "br-lan"
    elif [ -d "${base}/br-${net_if}/bridge" ]; then
        echo "br-${net_if}"
    else
        echo ""
    fi
}

ifname_collision() {
    local ifname="$1" my_section="$2"
    local result=0
    uci -X show wireless 2>/dev/null | grep '=wifi-iface' | while IFS='=' read -r sec _; do
        local sname=$(echo "$sec" | cut -d'.' -f2)
        [ "$sname" = "$my_section" ] && continue
        local d=$(uci -q get "wireless.${sname}.disabled" 2>/dev/null || echo "0")
        [ "$d" = "1" ] && continue
        local n=$(uci -q get "wireless.${sname}.ifname" 2>/dev/null || echo "")
        [ "$n" = "$ifname" ] && echo "1" && return 0
    done
    echo "0"
}

gen_config_minimal() {
    local ifname="$1" radio="$2" ssid="$3" enc="$4" key="$5" net_if="${6:-lan}"
    local bridge_if
    # resolve_bridge logic: lan → br-lan, else br-<net_if> (hostapd auto-creates)
    if [ "$net_if" = "lan" ]; then
        bridge_if="br-lan"
    else
        bridge_if="br-${net_if}"
    fi

    local conf="/tmp/test_hostapd.conf"
    cat > "$conf" << EOF
driver=nl80211
interface=${ifname}
ctrl_interface=/var/run/hostapd-${radio}
ssid=${ssid}
bridge=${bridge_if}
hw_mode=a
channel=auto
ieee80211n=1
ieee80211ac=1
ieee80211ax=1
ieee80211be=1
wmm_enabled=1
dtim_period=1
ignore_broadcast_ssid=0
noauth_pasn_activated=1
owe_ptk_workaround=1
send_probe_response=0
EOF

    if [ "$enc" = "none" ]; then
        echo "auth_algs=1" >> "$conf"
    else
        cat >> "$conf" << EOSEC
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
wpa_group_rekey=0
EOSEC
        [ -n "$key" ] && echo "wpa_passphrase=${key}" >> "$conf"
    fi
    echo "$conf"
}
