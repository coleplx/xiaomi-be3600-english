#!/bin/sh
# api.cgi - Dashboard API backend for Xiaomi BE3600
# Handles: overview, routing, firewall, syslog, processes, network, wireless
# Called by uhttpd CGI at http://router:8081/cgi-bin/api.cgi

# ── Authentication check ──
AUTH_PASS_FILE="/data/dashboard/.passwd"
if [ -f "$AUTH_PASS_FILE" ]; then
    AUTH_PASS=$(cat "$AUTH_PASS_FILE" 2>/dev/null)
    AUTH_HEADER="${HTTP_AUTHORIZATION:-}"

    if [ -z "$AUTH_HEADER" ]; then
        echo "Status: 401 Unauthorized"
        echo "WWW-Authenticate: Basic realm=\"BE3600 Dashboard\""
        echo "Content-Type: application/json"
        echo ""
        printf '{"code":401,"msg":"Authentication required"}'
        exit 0
    fi

    AUTH_B64=$(echo "$AUTH_HEADER" | sed 's/^Basic //')
    AUTH_DECODED=$(echo "$AUTH_B64" | base64 -d 2>/dev/null)
    AUTH_TRY="${AUTH_DECODED#*:}"

    if [ "$AUTH_TRY" != "$AUTH_PASS" ]; then
        echo "Status: 401 Unauthorized"
        echo "WWW-Authenticate: Basic realm=\"BE3600 Dashboard\""
        echo "Content-Type: application/json"
        echo ""
        printf '{"code":401,"msg":"Invalid credentials"}'
        exit 0
    fi
fi

echo "Content-Type: application/json"
echo ""

# Read query string or POST body
QS=""
if [ "$REQUEST_METHOD" = "POST" ]; then
    read -r QS
fi
[ -z "$QS" ] && QS="${QUERY_STRING:-}"

# Extract param value by key
get_param() {
    local key="$1"
    local val
    val=$(echo "$QS" | sed -n "s/.*[?&]${key}=\([^&]*\).*/\1/p")
    [ -z "$val" ] && val=$(echo "$QS" | sed -n "s/^${key}=\([^&]*\).*/\1/p")
    printf '%b' "${val//%/\\x}" | sed 's/+/ /g'
}

# JSON string escaper
json_esc() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\n/\\n/g'
}

# Format bytes to human readable
fmt_size() {
    local kb="$1"
    if [ "$kb" -gt 1048576 ]; then
        printf "%.1f GB" "$(echo "scale=1; $kb / 1048576" | bc 2>/dev/null || echo "?")"
    elif [ "$kb" -gt 1024 ]; then
        printf "%.1f MB" "$(echo "scale=1; $kb / 1024" | bc 2>/dev/null || echo "?")"
    else
        printf "%d KB" "$kb"
    fi
}

# Format uptime seconds to human readable
fmt_uptime() {
    local s="$1" d=0 h=0 m=0
    d=$((s / 86400)); s=$((s % 86400))
    h=$((s / 3600)); s=$((s % 3600))
    m=$((s / 60))
    if [ "$d" -gt 0 ]; then
        printf "%dd %dh %dm" "$d" "$h" "$m"
    elif [ "$h" -gt 0 ]; then
        printf "%dh %dm" "$h" "$m"
    else
        printf "%dm" "$m"
    fi
}

# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------
action_overview() {
    printf '{"code":0,"data":{'

    # Hostname
    hostname=$(cat /proc/sys/kernel/hostname 2>/dev/null || hostname 2>/dev/null || echo "Unknown")
    printf '"hostname":"%s",' "$(json_esc "$hostname")"

    # Model
    model=""
    [ -z "$model" ] && model=$(cat /tmp/sysinfo/model 2>/dev/null)
    [ -z "$model" ] && model=$(uci -q get system.@system[0].model 2>/dev/null)
    [ -z "$model" ] && model=$(grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' /etc/oui/oui_system.xml 2>/dev/null | head -1 | sed 's/.*:"\([^"]*\)".*/\1/')
    [ -z "$model" ] && model="Xiaomi BE3600"
    printf '"model":"%s",' "$(json_esc "$model")"

    # Firmware version
    fwver=""
    [ -z "$fwver" ] && [ -f /etc/openwrt_release ] && fwver=$(grep DISTRIB_RELEASE /etc/openwrt_release 2>/dev/null | cut -d"'" -f2)
    [ -z "$fwver" ] && [ -f /etc/xiaoqiang_version ] && fwver=$(head -1 /etc/xiaoqiang_version 2>/dev/null)
    [ -z "$fwver" ] && fwver="Unknown"
    printf '"firmware":"%s",' "$(json_esc "$fwver")"

    # Kernel version
    kver=$(uname -r 2>/dev/null || echo "Unknown")
    printf '"kernel":"%s",' "$(json_esc "$kver")"

    # Uptime
    uptime_sec=0
    [ -f /proc/uptime ] && uptime_sec=$(awk '{printf "%.0f", $1}' /proc/uptime 2>/dev/null)
    printf '"uptime":%s,' "$uptime_sec"
    printf '"uptime_str":"%s",' "$(json_esc "$(fmt_uptime "$uptime_sec")")"

    # CPU
    printf '"cpu":{'
    cores=$(grep -c ^processor /proc/cpuinfo 2>/dev/null || echo "2")
    printf '"cores":%s,' "$cores"
    arch=$(uname -m 2>/dev/null || echo "unknown")
    printf '"arch":"%s",' "$(json_esc "$arch")"
    load=$(cat /proc/loadavg 2>/dev/null || echo "0 0 0")
    load1=$(echo "$load" | awk '{print $1}')
    load5=$(echo "$load" | awk '{print $2}')
    load15=$(echo "$load" | awk '{print $3}')
    printf '"load_1m":%s,' "$load1"
    printf '"load_5m":%s,' "$load5"
    printf '"load_15m":%s' "$load15"
    printf '},'

    # Temperature (try common thermal zone paths)
    temp=""
    for tz in /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp1_input; do
        if [ -f "$tz" ]; then
            temp_raw=$(cat "$tz" 2>/dev/null)
            if [ -n "$temp_raw" ]; then
                temp=$((temp_raw / 1000))
                break
            fi
        fi
    done
    [ -z "$temp" ] && [ -f /sys/class/thermal/thermal_zone0/temp ] && temp=$(($(cat /sys/class/thermal/thermal_zone0/temp) / 1000))
    printf '"temperature":%s,' "${temp:--1}"

    # Memory
    printf '"memory":{'
    mem_tot=0; mem_free=0; mem_avail=0; mem_cached=0; mem_buffers=0
    [ -f /proc/meminfo ] && {
        mem_tot=$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)
        mem_free=$(awk '/^MemFree:/{print $2}' /proc/meminfo 2>/dev/null)
        mem_avail=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
        [ -z "$mem_avail" ] && mem_avail=$mem_free
        mem_cached=$(awk '/^Cached:/{print $2}' /proc/meminfo 2>/dev/null)
        mem_buffers=$(awk '/^Buffers:/{print $2}' /proc/meminfo 2>/dev/null)
    }
    mem_used=$((mem_tot - mem_avail))
    [ "$mem_used" -lt 0 ] && mem_used=$((mem_tot - mem_free))
    mem_pct=0
    [ "$mem_tot" -gt 0 ] && mem_pct=$((mem_used * 100 / mem_tot))
    printf '"total":%s,' "$mem_tot"
    printf '"used":%s,' "$mem_used"
    printf '"free":%s,' "$mem_free"
    printf '"cached":%s,' "$mem_cached"
    printf '"buffers":%s,' "$mem_buffers"
    printf '"percent":%s' "$mem_pct"
    printf '},'

    # Storage (df via temp file to avoid pipe subshell issues)
    printf '"storage":['
    tmpf="/tmp/api_storage_$$.tmp"
    df | tail -n +2 > "$tmpf" 2>/dev/null
    df_first=1
    while read -r line; do
        fs=$(echo "$line" | awk '{print $1}')
        size=$(echo "$line" | awk '{print $2}')
        used=$(echo "$line" | awk '{print $3}')
        avail=$(echo "$line" | awk '{print $4}')
        pct=$(echo "$line" | awk '{print $5}' | tr -d '%')
        mnt=$(echo "$line" | awk '{print $6}')
        [ $df_first -eq 0 ] && printf ","
        df_first=0
        printf '{"fs":"%s","size":"%s","used":"%s","avail":"%s","pct":"%s","mount":"%s"}' \
            "$(json_esc "$fs")" "$size" "$used" "$avail" "${pct:-0}" "$(json_esc "$mnt")"
    done < "$tmpf"
    rm -f "$tmpf"
    printf '],'

    # Network interfaces (via /sys/class/net to avoid pipe subshell issues)
    printf '"interfaces":['
    iface_first=1
    for iface_path in /sys/class/net/*/address; do
        [ -f "$iface_path" ] || continue
        idir="${iface_path%/address}"
        iname="${idir##*/}"
        [ "$iname" = "lo" ] && continue
        case "$iname" in wl*|bond*|gre*|gretap*|erspan*|ip6tnl*|ifb*|teql*|soc[0-9]*|mld-*|hostap_mld*|bhap_mld*|bhsta_mld*) continue ;; esac

        state=$(cat /sys/class/net/"$iname"/operstate 2>/dev/null || echo "down")
        mac=$(cat /sys/class/net/"$iname"/address 2>/dev/null || echo "")
        ips=$(ip -o addr show "$iname" 2>/dev/null | awk '/inet /{printf "%s,", $4}' | sed 's/,$//')
        rxpkt=$(cat /sys/class/net/"$iname"/statistics/rx_packets 2>/dev/null || echo 0)
        txpkt=$(cat /sys/class/net/"$iname"/statistics/tx_packets 2>/dev/null || echo 0)

        [ $iface_first -eq 0 ] && printf ","
        iface_first=0
        printf '{"name":"%s","state":"%s","mac":"%s","ips":"%s","rx_packets":%s,"tx_packets":%s}' \
            "$(json_esc "$iname")" "$state" "$(json_esc "$mac")" "$(json_esc "$ips")" "$rxpkt" "$txpkt"
    done
    printf '],'

    # Active connections
    conns=0
    [ -f /proc/net/nf_conntrack ] && conns=$(wc -l < /proc/net/nf_conntrack 2>/dev/null)
    [ "$conns" = "0" ] && [ -f /proc/net/ip_conntrack ] && conns=$(wc -l < /proc/net/ip_conntrack 2>/dev/null)
    printf '"connections":%s' "${conns:-0}"

    printf '}}'
}

# ---------------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------------
action_routing() {
    printf '{"code":0,"data":{'

    # IPv4 routes
    printf '"routes":['
    route_first=1
    ip -4 route show 2>/dev/null | while read -r line; do
        dest=$(echo "$line" | awk '{print $1}')
        gw=""
        dev=""
        [ "$dest" = "default" ] && { gw=$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1)}'); }
        if echo "$line" | grep -q "via "; then
            gw=$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1)}')
        fi
        if echo "$line" | grep -q "dev "; then
            dev=$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}')
        fi
        [ -z "$dev" ] && dev=""
        [ $route_first -eq 0 ] && printf ","
        route_first=0
        printf '{"dest":"%s","gw":"%s","dev":"%s"}' "$(json_esc "$dest")" "$(json_esc "${gw:-*}")" "$(json_esc "$dev")"
    done
    printf '],'

    # ARP table
    printf '"arp":['
    arp_first=1
    ip -4 neigh show 2>/dev/null | while read -r line; do
        nip=$(echo "$line" | awk '{print $1}')
        ndev=$(echo "$line" | awk '{print $3}')
        nmac=$(echo "$line" | awk '{print $5}')
        nstate=$(echo "$line" | awk '{print $NF}')
        [ -z "$nmac" ] && continue
        [ $arp_first -eq 0 ] && printf ","
        arp_first=0
        printf '{"ip":"%s","mac":"%s","dev":"%s","state":"%s"}' \
            "$(json_esc "$nip")" "$(json_esc "$nmac")" "$(json_esc "$ndev")" "$(json_esc "$nstate")"
    done
    printf '],'

    # Interface list with details (via /sys/class/net)
    printf '"ifaces":['
    iface_first=1
    for iface_path in /sys/class/net/*/address; do
        [ -f "$iface_path" ] || continue
        idir="${iface_path%/address}"
        iname="${idir##*/}"
        [ "$iname" = "lo" ] && continue

        state=$(cat /sys/class/net/"$iname"/operstate 2>/dev/null || echo "down")
        mac=$(cat "$iface_path" 2>/dev/null || echo "")
        ipaddr=$(ip -o addr show "$iname" 2>/dev/null | awk '/inet /{printf "%s,", $4}' | sed 's/,$//')

        [ $iface_first -eq 0 ] && printf ","
        iface_first=0
        printf '{"name":"%s","state":"%s","addr":"%s","mac":"%s"}' \
            "$(json_esc "$iname")" "$state" "$(json_esc "$ipaddr")" "$(json_esc "$mac")"
    done
    printf ']'

    printf '}}'
}

# ---------------------------------------------------------------------------
# FIREWALL
# ---------------------------------------------------------------------------
action_firewall() {
    printf '{"code":0,"data":{'

    # Filter table
    printf '"filter":"'
    iptables -L -n -v 2>/dev/null | sed 's/\\/\\\\/g; s/"/\\"/g' | while read -r line; do
        printf '%s\\n' "$line"
    done
    printf '",'

    # NAT table
    printf '"nat":"'
    iptables -t nat -L -n -v 2>/dev/null | sed 's/\\/\\\\/g; s/"/\\"/g' | while read -r line; do
        printf '%s\\n' "$line"
    done
    printf '",'

    # Zone definitions from UCI
    printf '"zones":['
    zone_first=1
    tmpf="/tmp/api_fw_zones.tmp"
    uci -X show firewall 2>/dev/null | grep '=zone' > "$tmpf" 2>/dev/null
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        zname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$zname" ] && continue
        z_input=$(uci -q get "firewall.${zname}.input" 2>/dev/null || echo "")
        z_output=$(uci -q get "firewall.${zname}.output" 2>/dev/null || echo "")
        z_forward=$(uci -q get "firewall.${zname}.forward" 2>/dev/null || echo "")
        z_network=$(uci -q get "firewall.${zname}.network" 2>/dev/null || echo "")
        [ $zone_first -eq 0 ] && printf ","
        zone_first=0
        printf '{"name":"%s","input":"%s","output":"%s","forward":"%s","network":"%s"}' \
            "$(json_esc "$zname")" "$(json_esc "$z_input")" "$(json_esc "$z_output")" \
            "$(json_esc "$z_forward")" "$(json_esc "$z_network")"
    done < "$tmpf"
    rm -f "$tmpf"
    printf ']'

    printf '}}'
}

# ---------------------------------------------------------------------------
# SYSTEM LOG
# ---------------------------------------------------------------------------
action_syslog() {
    lines_param=$(get_param "lines")
    nlines=${lines_param:-100}
    case "$nlines" in ''|*[!0-9]*) nlines=100 ;; esac

    printf '{"code":0,"data":{"lines":['
    first=1
    cat /tmp/messages 2>/dev/null | tail -n "$nlines" | while read -r line; do
        [ $first -eq 0 ] && printf ","
        first=0
        printf '"%s"' "$(json_esc "$line")"
    done
    printf ']}}'
}

# ---------------------------------------------------------------------------
# PROCESSES
# ---------------------------------------------------------------------------
action_processes() {
    printf '{"code":0,"data":{"processes":['
    first=1
    # ps output: PID USER VSZ STAT COMMAND
    # busybox ps: PID USER TIME COMMAND or PID Uid VmSize Stat Command
    ps w 2>/dev/null | tail -n +2 | while read -r line; do
        pid=$(echo "$line" | awk '{print $1}')
        user=$(echo "$line" | awk '{print $2}')
        # Rest is command - varies by busybox version
        # Try to extract CPU/MEM if available
        vsz=$(echo "$line" | awk '{print $3}')
        stat=$(echo "$line" | awk '{print $4}')
        cmd=$(echo "$line" | awk '{for(i=5;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ $//')

        # If VSZ looks like a time (HH:MM), then no VSZ available
        if echo "$vsz" | grep -q ':'; then
            cmd=$(echo "$line" | awk '{for(i=3;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ $//')
            vsz=""
            stat=""
        fi

        [ -z "$pid" ] && continue
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"pid":%s,"user":"%s","vsz":"%s","stat":"%s","cmd":"%s"}' \
            "${pid:-0}" "$(json_esc "$user")" "$(json_esc "${vsz:-}")" \
            "$(json_esc "${stat:-}")" "$(json_esc "$cmd")"
    done
    printf ']}}'
}

# -- All Running Services with Memory --------------------------------
action_ps_mem() {
    printf '{"code":0,"data":{"processes":['
    local first=1
    for pid in $(ls /proc/ | grep -E "^[1-9][0-9]*$" | sort -n); do
        [ -r /proc/$pid/status ] || continue
        local name rss state
        name=$(cat /proc/$pid/comm 2>/dev/null)
        rss=$(grep "^VmRSS:" /proc/$pid/status 2>/dev/null | awk '{print $2}')
        state=$(grep "^State:" /proc/$pid/status 2>/dev/null | awk '{print $2}')
        [ -z "$rss" ] && rss=0
        [ "$rss" = "0" ] && continue
        local cmdline=""
        if [ -r /proc/$pid/cmdline ]; then
            cmdline=$(tr '\0\011\012\015' ' ' < /proc/$pid/cmdline 2>/dev/null | sed 's/  */ /g; s/^ *//; s/ *$//')
        fi
        [ -z "$cmdline" ] && cmdline="[$name]"
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"pid":%s,"name":"%s","rss":%s,"state":"%s","cmd":"%s"}' \
            "$pid" "$(json_esc "$name")" "$rss" \
            "$(json_esc "$state")" "$(json_esc "$cmdline")"
    done
    printf ']}}'
}

# ---------------------------------------------------------------------------
# NETWORK INTERFACES
# ---------------------------------------------------------------------------
action_list_ifaces() {
    printf '{"code":0,"data":{"interfaces":['
    first=1
    tmpf="/tmp/api_net_ifaces.tmp"
    uci -X show network 2>/dev/null | grep '=interface' > "$tmpf"
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        iname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$iname" ] && continue

        proto=$(uci -q get "network.${iname}.proto" 2>/dev/null || echo "")
        ipaddr=$(uci -q get "network.${iname}.ipaddr" 2>/dev/null || echo "")
        netmask=$(uci -q get "network.${iname}.netmask" 2>/dev/null || echo "")
        gateway=$(uci -q get "network.${iname}.gateway" 2>/dev/null || echo "")
        dns=$(uci -q get "network.${iname}.dns" 2>/dev/null || echo "")
        ifname=$(uci -q get "network.${iname}.ifname" 2>/dev/null || echo "")
        wantype=$(uci -q get "network.${iname}.wantype" 2>/dev/null || echo "")
        itype=$(uci -q get "network.${iname}.type" 2>/dev/null || echo "")
        disabled=$(uci -q get "network.${iname}.disabled" 2>/dev/null || echo "0")

        # Resolve device display: ifname may be empty (wantype interfaces)
        device_display="$ifname"
        [ -z "$device_display" ] && [ -n "$wantype" ] && device_display="auto ($wantype)"

        # Find firewall zone this interface belongs to
        zone=""
        ztmp="/tmp/api_iface_zone_$$.tmp"
        uci -X show firewall 2>/dev/null | grep '=zone' > "$ztmp"
        while IFS='=' read -r zsec _; do
            [ -z "$zsec" ] && continue
            zsection=$(echo "$zsec" | cut -d'.' -f2)
            [ -z "$zsection" ] && continue
            znet=$(uci -q get "firewall.${zsection}.network" 2>/dev/null || echo "")
            # Check if interface name is in this zone's network list
            for zn in $znet; do
                [ "$zn" = "$iname" ] && zone=$(uci -q get "firewall.${zsection}.name" 2>/dev/null || echo "$zsection")
            done
        done < "$ztmp"
        rm -f "$ztmp"

        # Skip device-only stub interfaces (no proto, no IP, no wantype, not a bridge)
        [ -z "$proto" ] && [ -z "$ipaddr" ] && [ -z "$wantype" ] && [ "$itype" != "bridge" ] && continue

        # Determine state: check first physical device in ifname
        state="down"
        main_dev=$(echo "$ifname" | awk '{print $1}')
        [ -z "$main_dev" ] && main_dev="br-${iname}"
        [ -f "/sys/class/net/${main_dev}/operstate" ] && state=$(cat "/sys/class/net/${main_dev}/operstate" 2>/dev/null || echo "down")

        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"name":"%s","proto":"%s","ipaddr":"%s","netmask":"%s","gateway":"%s","dns":"%s","ifname":"%s","type":"%s","state":"%s","zone":"%s","wantype":"%s","disabled":"%s"}' \
            "$(json_esc "$iname")" "$(json_esc "$proto")" "$(json_esc "$ipaddr")" \
            "$(json_esc "$netmask")" "$(json_esc "$gateway")" "$(json_esc "$dns")" \
            "$(json_esc "$device_display")" "$(json_esc "$itype")" "$(json_esc "$state")" "$(json_esc "$zone")" \
            "$(json_esc "$wantype")" "$disabled"
    done < "$tmpf"
    rm -f "$tmpf"
    printf ']}}'
}

action_edit_iface() {
    iname=$(get_param "name")
    proto=$(get_param "proto")
    ipaddr=$(get_param "ipaddr")
    netmask=$(get_param "netmask")
    gateway=$(get_param "gateway")
    dns=$(get_param "dns")
    new_ifname=$(get_param "ifname")

    [ -z "$iname" ] && { printf '{"code":1,"msg":"Interface name required"}'; return; }
    if ! uci -q get "network.${iname}" > /dev/null 2>&1; then
        printf '{"code":1,"msg":"Interface not found: %s"}' "$(json_esc "$iname")"
        return
    fi

    new_zone=$(get_param "zone")

    [ -n "$new_ifname" ] && uci set "network.${iname}.ifname=${new_ifname}"
    [ -n "$proto" ] && uci set "network.${iname}.proto=${proto}"
    [ -n "$ipaddr" ] && uci set "network.${iname}.ipaddr=${ipaddr}"
    [ -n "$netmask" ] && uci set "network.${iname}.netmask=${netmask}"
    [ -n "$gateway" ] && uci set "network.${iname}.gateway=${gateway}"

    # DNS can be cleared with empty value
    if [ -n "$dns" ]; then
        uci set "network.${iname}.dns=${dns}"
    elif get_param "dns_clear" > /dev/null 2>&1; then
        dns_clr=$(get_param "dns_clear")
        [ "$dns_clr" = "1" ] && uci delete "network.${iname}.dns" 2>/dev/null
    fi

    # Firewall zone reassignment
    if [ -n "$new_zone" ]; then
        # Remove this interface from all existing zones
        ztmp="/tmp/api_zone_move_$$.tmp"
        uci -X show firewall 2>/dev/null | grep '=zone' > "$ztmp"
        while IFS='=' read -r zsec _; do
            [ -z "$zsec" ] && continue
            zsection=$(echo "$zsec" | cut -d'.' -f2)
            [ -z "$zsection" ] && continue
            # Delete this interface from the zone's network list if present
            uci del_list "firewall.${zsection}.network=${iname}" 2>/dev/null
        done < "$ztmp"
        rm -f "$ztmp"
        # Find the target zone section (by name) and add interface to it
        # Reread zone list to find the section with matching name
        zfound=0
        uci -X show firewall 2>/dev/null | grep '=zone' > "$ztmp"
        while IFS='=' read -r zsec _; do
            [ -z "$zsec" ] && continue
            zsection=$(echo "$zsec" | cut -d'.' -f2)
            [ -z "$zsection" ] && continue
            zname_val=$(uci -q get "firewall.${zsection}.name" 2>/dev/null || echo "$zsection")
            if [ "$zname_val" = "$new_zone" ]; then
                uci add_list "firewall.${zsection}.network=${iname}" 2>/dev/null
                zfound=1
                break
            fi
        done < "$ztmp"
        rm -f "$ztmp"
        uci commit firewall
    fi

    uci commit network

    # Apply changes to this interface only (safer than full network restart)
    ifup "$iname" 2>/dev/null || true

    printf '{"code":0,"msg":"Interface %s updated"}' "$(json_esc "$iname")"
}

# ---------------------------------------------------------------------------
# WIRELESS
# ---------------------------------------------------------------------------
action_list_wireless() {
    printf '{"code":0,"data":{"radios":['

    radio_first=1
    tmpf="/tmp/api_wifi_radios.tmp"
    uci -X show wireless 2>/dev/null | grep '=wifi-device' > "$tmpf"
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        rname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$rname" ] && continue

        channel=$(uci -q get "wireless.${rname}.channel" 2>/dev/null || echo "auto")
        htmode=$(uci -q get "wireless.${rname}.htmode" 2>/dev/null || echo "")
        hwmode=$(uci -q get "wireless.${rname}.hwmode" 2>/dev/null || echo "")
        txpower=$(uci -q get "wireless.${rname}.txpower" 2>/dev/null || echo "")
        disabled=$(uci -q get "wireless.${rname}.disabled" 2>/dev/null || echo "0")

        # Band label
        band="2g"
        case "$rname" in *5*|*wifi1*) band="5g" ;; esac
        case "$hwmode" in *a*) band="5g" ;; esac

        # Radio state: check if wifi device is up
        rstate="down"
        iw dev "$rname" info >/dev/null 2>&1 && rstate="up"
        [ "$disabled" = "1" ] && rstate="disabled"

        [ $radio_first -eq 0 ] && printf ","
        radio_first=0

        printf '{"name":"%s","band":"%s","channel":"%s","htmode":"%s","hwmode":"%s","txpower":"%s","disabled":"%s","state":"%s","vaps":[' \
            "$(json_esc "$rname")" "$band" "$(json_esc "$channel")" "$(json_esc "$htmode")" \
            "$(json_esc "$hwmode")" "$(json_esc "$txpower")" "$disabled" "$rstate"

        # VAPs on this radio
        vap_first=1
        tmpv="/tmp/api_wifi_vaps_$$.tmp"
        uci -X show wireless 2>/dev/null | grep '=wifi-iface' > "$tmpv"
        while IFS='=' read -r vsec _; do
            [ -z "$vsec" ] && continue
            vname=$(echo "$vsec" | cut -d'.' -f2)
            [ -z "$vname" ] && continue
            vdev=$(uci -q get "wireless.${vname}.device" 2>/dev/null || echo "")
            [ "$vdev" != "$rname" ] && continue

            vssid=$(uci -q get "wireless.${vname}.ssid" 2>/dev/null || echo "")
            vmode=$(uci -q get "wireless.${vname}.mode" 2>/dev/null || echo "ap")
            venc=$(uci -q get "wireless.${vname}.encryption" 2>/dev/null || echo "none")
            vnet=$(uci -q get "wireless.${vname}.network" 2>/dev/null || echo "lan")
            vdisabled=$(uci -q get "wireless.${vname}.disabled" 2>/dev/null || echo "0")
            vhidden=$(uci -q get "wireless.${vname}.hidden" 2>/dev/null || echo "0")
            vifname=$(uci -q get "wireless.${vname}.ifname" 2>/dev/null || echo "")
            vextra=$(uci -q get "wireless.${vname}.extra_wifi" 2>/dev/null || echo "0")

            # VAP state: check if ifname exists and is up
            vstate="down"
            [ -n "$vifname" ] && iw dev "$vifname" info >/dev/null 2>&1 && vstate="up"
            [ "$vdisabled" = "1" ] && vstate="disabled"

            [ $vap_first -eq 0 ] && printf ","
            vap_first=0
            printf '{"section":"%s","ssid":"%s","mode":"%s","encryption":"%s","network":"%s","disabled":"%s","hidden":"%s","ifname":"%s","state":"%s","extra_wifi":"%s"}' \
                "$(json_esc "$vname")" "$(json_esc "$vssid")" "$(json_esc "$vmode")" \
                "$(json_esc "$venc")" "$(json_esc "$vnet")" "$vdisabled" \
                "$vhidden" "$(json_esc "$vifname")" "$vstate" "$vextra"
        done < "$tmpv"
        rm -f "$tmpv"

        printf ']}'
    done < "$tmpf"
    rm -f "$tmpf"
    printf ']}}'
}

action_edit_wifi_iface() {
    section=$(get_param "section")
    ssid=$(get_param "ssid")
    encryption=$(get_param "encryption")
    key=$(get_param "key")
    disabled=$(get_param "disabled")
    hidden=$(get_param "hidden")
    channel=$(get_param "channel")
    htmode=$(get_param "htmode")
    txpower=$(get_param "txpower")
    is_radio=$(get_param "is_radio")

    [ -z "$section" ] && { printf '{"code":1,"msg":"Section name required"}'; return; }

    exists=$(uci -q get "wireless.${section}" 2>/dev/null)
    [ -z "$exists" ] && { printf '{"code":1,"msg":"Wireless section not found: %s"}' "$(json_esc "$section")"; return; }

    # If it's a radio (wifi-device), edit radio settings
    if [ "$is_radio" = "1" ]; then
        [ -n "$channel" ] && uci set "wireless.${section}.channel=${channel}"
        [ -n "$htmode" ] && uci set "wireless.${section}.htmode=${htmode}"
        [ -n "$txpower" ] && uci set "wireless.${section}.txpower=${txpower}"
        [ -n "$disabled" ] && uci set "wireless.${section}.disabled=${disabled}"
        uci commit wireless
        printf '{"code":0,"msg":"Radio %s updated. WiFi restart may be needed."}' "$(json_esc "$section")"
        return
    fi

    # VAP (wifi-iface) settings
    [ -n "$ssid" ] && uci set "wireless.${section}.ssid=${ssid}"
    [ -n "$encryption" ] && uci set "wireless.${section}.encryption=${encryption}"
    [ -n "$disabled" ] && uci set "wireless.${section}.disabled=${disabled}"
    [ -n "$hidden" ] && uci set "wireless.${section}.hidden=${hidden}"

    # Key: only set if encryption is not "none" and key is provided
    if [ "$encryption" = "none" ]; then
        uci delete "wireless.${section}.key" 2>/dev/null
    elif [ -n "$key" ]; then
        [ ${#key} -ge 8 ] && uci set "wireless.${section}.key=${key}"
    fi

    uci commit wireless

    printf '{"code":0,"msg":"VAP %s updated. WiFi restart may be needed."}' "$(json_esc "$section")"
}

action_create_wifi_vap() {
    band_val=$(get_param "band")
    ssid_val=$(get_param "ssid")
    encryption_val=$(get_param "encryption")
    key_val=$(get_param "key")
    network_val=$(get_param "network")

    [ -z "$ssid_val" ] && { printf '{"code":1,"msg":"SSID required"}'; return; }
    [ -z "$band_val" ] && band_val="both"
    [ -z "$encryption_val" ] && encryption_val="psk2"
    [ -z "$network_val" ] && network_val="lan"

    if [ "$encryption_val" != "none" ] && [ -z "$key_val" ]; then
        printf '{"code":1,"msg":"Password required for encrypted networks"}'; return
    fi
    if [ -n "$key_val" ] && [ ${#key_val} -lt 8 ] && [ "$encryption_val" != "none" ]; then
        printf '{"code":1,"msg":"Password must be at least 8 characters"}'; return
    fi

    if [ "$band_val" = "both" ]; then
        idx1=$(uci add wireless wifi-iface 2>/dev/null)
        idx2=$(uci add wireless wifi-iface 2>/dev/null)
        uci set "wireless.${idx1}.device=wifi0"
        uci set "wireless.${idx1}.network=${network_val}"
        uci set "wireless.${idx1}.mode=ap"
        uci set "wireless.${idx1}.ssid=${ssid_val}"
        uci set "wireless.${idx1}.encryption=${encryption_val}"
        uci set "wireless.${idx1}.disabled=0"
        [ -n "$key_val" ] && uci set "wireless.${idx1}.key=${key_val}"
        uci set "wireless.${idx2}.device=wifi1"
        uci set "wireless.${idx2}.network=${network_val}"
        uci set "wireless.${idx2}.mode=ap"
        uci set "wireless.${idx2}.ssid=${ssid_val}"
        uci set "wireless.${idx2}.encryption=${encryption_val}"
        uci set "wireless.${idx2}.disabled=0"
        [ -n "$key_val" ] && uci set "wireless.${idx2}.key=${key_val}"
        uci commit wireless
        sh /data/dashboard/apply_vap.sh create "$idx1" >/dev/null 2>&1 &
        sh /data/dashboard/apply_vap.sh create "$idx2" >/dev/null 2>&1 &
    else
        device="wifi0"
        [ "$band_val" = "5g" ] && device="wifi1"
        idx=$(uci add wireless wifi-iface 2>/dev/null)
        [ -z "$idx" ] && { printf '{"code":1,"msg":"Failed to create UCI section"}'; return; }
        uci set "wireless.${idx}.device=${device}"
        uci set "wireless.${idx}.network=${network_val}"
        uci set "wireless.${idx}.mode=ap"
        uci set "wireless.${idx}.ssid=${ssid_val}"
        uci set "wireless.${idx}.encryption=${encryption_val}"
        uci set "wireless.${idx}.disabled=0"
        [ -n "$key_val" ] && uci set "wireless.${idx}.key=${key_val}"
        uci commit wireless
        sh /data/dashboard/apply_vap.sh create "$idx" >/dev/null 2>&1 &
    fi

    printf '{"code":0,"msg":"VAP %s created"}' "$(json_esc "$ssid_val")"
}

action_delete_wifi_vap() {
    section=$(get_param "section")
    [ -z "$section" ] && { printf '{"code":1,"msg":"Section name required"}'; return; }

    # Protect core VAPs
    case "$section" in
        miot_*|bh_ap_*|bhsta_*|[012]) printf '{"code":1,"msg":"Cannot delete core VAP"}'; return ;;
    esac

    exists=$(uci -q get "wireless.${section}" 2>/dev/null)
    [ -z "$exists" ] && { printf '{"code":1,"msg":"VAP not found"}'; return; }

    ifname_val=$(uci -q get "wireless.${section}.ifname" 2>/dev/null)
    uci delete "wireless.${section}" 2>/dev/null
    uci commit wireless

    sh /data/dashboard/apply_vap.sh delete "$section" "$ifname_val" >/dev/null 2>&1 &

    printf '{"code":0,"msg":"VAP deleted"}'
}

# ---------------------------------------------------------------------------
# NETWORK DEVICES
# ---------------------------------------------------------------------------
action_list_devices() {
    printf '{"code":0,"data":{"devices":['
    first=1

    for iface_path in /sys/class/net/*/address; do
        [ -f "$iface_path" ] || continue
        idir="${iface_path%/address}"
        dname="${idir##*/}"

        # Skip virtual devices that clutter the view
        case "$dname" in
            lo|bond0|gre0|gretap0|erspan0|ip6tnl0|ifb*|teql*) continue ;;
        esac

        # Skip system-internal devices managed by kernel/wifi drivers
        case "$dname" in
            soc[0-9]*|mld-*|hostap_mld*|bhap_mld*|bhsta_mld*) continue ;;
        esac

        state=$(cat "/sys/class/net/${dname}/operstate" 2>/dev/null || echo "unknown")
        mac=$(cat "/sys/class/net/${dname}/address" 2>/dev/null || echo "")
        mtu=$(cat "/sys/class/net/${dname}/mtu" 2>/dev/null || echo "1500")
        speed=""
        [ -f "/sys/class/net/${dname}/speed" ] && speed=$(cat "/sys/class/net/${dname}/speed" 2>/dev/null)

        # Determine device type
        dtype="phy"
        vlan_parent=""
        vlan_id=""
        bridge_ports=""

        # Check if it's a VLAN subinterface (e.g., eth1.100)
        if echo "$dname" | grep -q '\.'; then
            dtype="vlan"
            vlan_parent="${dname%.*}"
            vlan_id="${dname##*.}"
            case "$vlan_id" in ''|*[!0-9]*) dtype="other"; vlan_id="" ;; esac
        fi

        # Check if it's a bridge
        if [ -d "/sys/class/net/${dname}/bridge" ]; then
            dtype="bridge"
            bridge_ports=$(ls "/sys/class/net/${dname}/brif" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
        fi

        # Check if it's a wifi radio
        case "$dname" in wifi*|wl*) dtype="wifi" ;; esac

        # Check if it's mld/hostap/bh (mesh/backhaul virtual)
        case "$dname" in *_mld*|hostap_*|bhap_*|bhsta_*|mld-*) dtype="virtual" ;; esac

        # Find which interfaces use this device
        used_by=""
        used_tmp="/tmp/api_dev_used_$$.tmp"
        uci -X show network 2>/dev/null | grep '=interface' | while IFS='=' read -r sec _; do
            uname=$(echo "$sec" | cut -d'.' -f2)
            uifname=$(uci -q get "network.${uname}.ifname" 2>/dev/null)
            # Check if the device name appears in ifname list
            for w in $uifname; do
                [ "$w" = "$dname" ] && printf '%s,' "$uname" >> "$used_tmp"
            done
            # Check bridge name match (br-lan → lan interface)
            [ "br-${uname}" = "$dname" ] && printf '%s,' "$uname" >> "$used_tmp"
        done
        [ -f "$used_tmp" ] && { used_by=$(tr ',' '\n' < "$used_tmp" | sort -u | tr '\n' ',' | sed 's/,$//'); rm -f "$used_tmp"; }

        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"name":"%s","type":"%s","state":"%s","mac":"%s","mtu":"%s","speed":"%s","vlan_parent":"%s","vlan_id":"%s","bridge_ports":"%s","used_by":"%s"}' \
            "$(json_esc "$dname")" "$dtype" "$(json_esc "$state")" "$(json_esc "$mac")" "$mtu" "${speed:-}" \
            "$(json_esc "$vlan_parent")" "$(json_esc "$vlan_id")" "$(json_esc "$bridge_ports")" "$(json_esc "$used_by")"
    done
    printf ']}}'
}

action_create_device() {
    dtype=$(get_param "type")
    dname=$(get_param "name")

    case "$dtype" in
        vlan)
            base_dev=$(get_param "base_device")
            vlan_id=$(get_param "vlan_id")
            [ -z "$base_dev" ] && { printf '{"code":1,"msg":"Base device required"}'; return; }
            [ -z "$vlan_id" ] && { printf '{"code":1,"msg":"VLAN ID required"}'; return; }
            case "$vlan_id" in ''|*[!0-9]*) printf '{"code":1,"msg":"Invalid VLAN ID"}'; return ;; esac
            [ "$vlan_id" -lt 1 ] || [ "$vlan_id" -gt 4094 ] && { printf '{"code":1,"msg":"VLAN ID must be 1-4094"}'; return; }

            vdev="${base_dev}.${vlan_id}"

            # Check if already exists
            [ -d "/sys/class/net/${vdev}" ] && { printf '{"code":1,"msg":"Device %s already exists"}' "$(json_esc "$vdev")"; return; }

            # Create VLAN subinterface
            ip link add link "$base_dev" name "$vdev" type vlan id "$vlan_id" 2>/dev/null || \
                { printf '{"code":1,"msg":"Failed to create VLAN device"}'; return; }
            ip link set "$vdev" up 2>/dev/null

            # UCI: create interface for persistence
            iname="vlan_${vlan_id}"
            macaddr=$(cat "/sys/class/net/${base_dev}/address" 2>/dev/null || echo "")
            uci set "network.${iname}=interface"
            uci set "network.${iname}.ifname=${vdev}"
            uci set "network.${iname}.type=bridge"
            uci set "network.${iname}.proto=none"
            [ -n "$macaddr" ] && uci set "network.${iname}.macaddr=${macaddr}"
            uci commit network

            # Add to br-vlan_X bridge
            br="br-${iname}"
            brctl addbr "$br" 2>/dev/null
            brctl addif "$br" "$vdev" 2>/dev/null
            ip link set "$br" up 2>/dev/null

            printf '{"code":0,"msg":"VLAN device %s created"}' "$(json_esc "$vdev")"
            ;;

        bridge)
            [ -z "$dname" ] && { printf '{"code":1,"msg":"Bridge name required"}'; return; }
            ports=$(get_param "ports")
            [ -z "$ports" ] && { printf '{"code":1,"msg":"At least one port required"}'; return; }

            br="br-${dname}"
            [ -d "/sys/class/net/${br}/bridge" ] && { printf '{"code":1,"msg":"Bridge %s already exists"}' "$(json_esc "$br")"; return; }

            brctl addbr "$br" 2>/dev/null || { printf '{"code":1,"msg":"Failed to create bridge"}'; return; }

            for port in $ports; do
                [ -d "/sys/class/net/${port}" ] && brctl addif "$br" "$port" 2>/dev/null
            done
            ip link set "$br" up 2>/dev/null

            # UCI
            iname="$dname"
            uci set "network.${iname}=interface"
            uci set "network.${iname}.ifname=${ports}"
            uci set "network.${iname}.type=bridge"
            uci set "network.${iname}.proto=none"
            uci commit network

            printf '{"code":0,"msg":"Bridge %s created"}' "$(json_esc "$br")"
            ;;

        *) printf '{"code":1,"msg":"Unknown device type: %s"}' "$(json_esc "$dtype")" ;;
    esac
}

action_delete_device() {
    dname=$(get_param "name")
    [ -z "$dname" ] && { printf '{"code":1,"msg":"Device name required"}'; return; }

    [ ! -d "/sys/class/net/${dname}" ] && { printf '{"code":1,"msg":"Device not found"}'; return; }

    # Don't allow deleting physical devices
    is_phy=0
    [ -d "/sys/class/net/${dname}/device" ] && is_phy=1
    # Also protect main bridge and wifi
    case "$dname" in br-lan|wifi*|eth0|eth1) is_phy=1 ;; esac
    [ "$is_phy" -eq 1 ] && { printf '{"code":1,"msg":"Cannot delete physical/core device"}'; return; }

    # Remove from any bridge
    bridge=$(brctl show 2>/dev/null | grep "$dname" | awk '{print $1}')
    [ -n "$bridge" ] && brctl delif "$bridge" "$dname" 2>/dev/null

    # If it's a bridge itself, remove all ports
    [ -d "/sys/class/net/${dname}/bridge" ] && ip link del "$dname" 2>/dev/null

    # Delete VLAN subinterface
    ip link del "$dname" 2>/dev/null

    # Remove UCI reference
    # Find interfaces pointing to this device and remove the device from ifname
    tmpf="/tmp/api_deldev_$$.tmp"
    uci -X show network 2>/dev/null | grep '=interface' > "$tmpf"
    while IFS='=' read -r sec _; do
        uname=$(echo "$sec" | cut -d'.' -f2)
        uifname=$(uci -q get "network.${uname}.ifname" 2>/dev/null)
        # Remove the device from ifname list
        new_ifname=$(echo "$uifname" | sed "s/${dname}//g" | sed 's/  / /g' | sed 's/^ //;s/ $//')
        if [ -z "$new_ifname" ]; then
            uci delete "network.${uname}" 2>/dev/null
        elif [ "$new_ifname" != "$uifname" ]; then
            uci set "network.${uname}.ifname=${new_ifname}"
        fi
    done < "$tmpf"
    rm -f "$tmpf"
    uci commit network

    printf '{"code":0,"msg":"Device %s deleted"}' "$(json_esc "$dname")"
}

action_create_iface() {
    iname=$(get_param "name")
    proto=$(get_param "proto")
    device=$(get_param "device")
    ipaddr=$(get_param "ipaddr")
    netmask=$(get_param "netmask")
    gateway=$(get_param "gateway")
    dns=$(get_param "dns")

    [ -z "$iname" ] && { printf '{"code":1,"msg":"Interface name required"}'; return; }
    [ -z "$proto" ] && proto="static"
    [ -z "$device" ] && { printf '{"code":1,"msg":"Device required"}'; return; }

    # Check if interface name already exists
    if uci -q get "network.${iname}" > /dev/null 2>&1; then
        printf '{"code":1,"msg":"Interface %s already exists"}' "$(json_esc "$iname")"
        return
    fi

    uci set "network.${iname}=interface"
    uci set "network.${iname}.ifname=${device}"
    uci set "network.${iname}.proto=${proto}"
    [ -n "$ipaddr" ] && uci set "network.${iname}.ipaddr=${ipaddr}"
    [ -n "$netmask" ] && uci set "network.${iname}.netmask=${netmask}"
    [ -n "$gateway" ] && uci set "network.${iname}.gateway=${gateway}"
    [ -n "$dns" ] && uci set "network.${iname}.dns=${dns}"
    uci commit network

    # Bring up the interface
    ifup "$iname" 2>/dev/null || true

    printf '{"code":0,"msg":"Interface %s created"}' "$(json_esc "$iname")"
}

action_delete_iface() {
    iname=$(get_param "name")
    [ -z "$iname" ] && { printf '{"code":1,"msg":"Interface name required"}'; return; }

    # Protect core interfaces
    case "$iname" in lan|wan|loopback|miot)
        printf '{"code":1,"msg":"Cannot delete core interface: %s"}' "$(json_esc "$iname")"
        return
        ;;
    esac

    if ! uci -q get "network.${iname}" > /dev/null 2>&1; then
        printf '{"code":1,"msg":"Interface not found"}'; return
    fi

    uci delete "network.${iname}" 2>/dev/null
    uci commit network

    printf '{"code":0,"msg":"Interface %s deleted"}' "$(json_esc "$iname")"
}

# ---------------------------------------------------------------------------
# DHCP & DNS
# ---------------------------------------------------------------------------
action_dhcp_config() {
    printf '{"code":0,"data":{'

    # dnsmasq global settings
    printf '"dnsmasq":{'
    printf '"domainneeded":"%s",' "$(uci -q get dhcp.@dnsmasq[0].domainneeded 2>/dev/null || echo 1)"
    printf '"boguspriv":"%s",' "$(uci -q get dhcp.@dnsmasq[0].boguspriv 2>/dev/null || echo 1)"
    printf '"localise_queries":"%s",' "$(uci -q get dhcp.@dnsmasq[0].localise_queries 2>/dev/null || echo 1)"
    printf '"rebind_protection":"%s",' "$(uci -q get dhcp.@dnsmasq[0].rebind_protection 2>/dev/null || echo 0)"
    printf '"authoritative":"%s",' "$(uci -q get dhcp.@dnsmasq[0].authoritative 2>/dev/null || echo 1)"
    printf '"allservers":"%s",' "$(uci -q get dhcp.@dnsmasq[0].allservers 2>/dev/null || echo 1)"
    printf '"local":"%s",' "$(uci -q get dhcp.@dnsmasq[0].local 2>/dev/null || echo "")"
    printf '"expandhosts":"%s"' "$(uci -q get dhcp.@dnsmasq[0].expandhosts 2>/dev/null || echo 1)"
    printf '},'

    # DHCP pools (per interface)
    printf '"pools":['
    pool_first=1
    tmpf="/tmp/api_dhcp_pools.tmp"
    uci -X show dhcp 2>/dev/null | grep '=dhcp' > "$tmpf"
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        pname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$pname" ] && continue
        # Skip dnsmasq and odhcpd sections
        case "$pname" in @*|odhcpd) continue ;; esac
        # Verify it's actually a dhcp section (not a leftover)
        ptype=$(uci -q get "dhcp.${pname}.interface" 2>/dev/null)
        [ -z "$ptype" ] && continue

        piface="$ptype"
        pstart=$(uci -q get "dhcp.${pname}.start" 2>/dev/null || echo "100")
        plimit=$(uci -q get "dhcp.${pname}.limit" 2>/dev/null || echo "150")
        plead=$(uci -q get "dhcp.${pname}.leasetime" 2>/dev/null || echo "12h")
        pignore=$(uci -q get "dhcp.${pname}.ignore" 2>/dev/null || echo "0")
        pforce=$(uci -q get "dhcp.${pname}.force" 2>/dev/null || echo "0")

        # Get interface IP/netmask for range display
        pipaddr=$(uci -q get "network.${piface}.ipaddr" 2>/dev/null || echo "")
        pnetmask=$(uci -q get "network.${piface}.netmask" 2>/dev/null || echo "")

        # Get dhcp_option list (pipe-separated since values contain commas)
        popts=""
        opttmp="/tmp/api_dhcp_opts_$$.tmp"
        uci -q get "dhcp.${pname}.dhcp_option" 2>/dev/null | tr ' ' '\n' > "$opttmp" 2>/dev/null
        while read -r optline; do
            [ -z "$optline" ] && continue
            [ -n "$popts" ] && popts="${popts}|"
            popts="${popts}${optline}"
        done < "$opttmp"
        rm -f "$opttmp"

        [ $pool_first -eq 0 ] && printf ","
        pool_first=0
        printf '{"section":"%s","interface":"%s","start":"%s","limit":"%s","leasetime":"%s","ignore":"%s","force":"%s","ipaddr":"%s","netmask":"%s","dhcp_options":"%s"}' \
            "$(json_esc "$pname")" "$(json_esc "$piface")" "$pstart" "$plimit" "$plead" "$pignore" "$pforce" \
            "$(json_esc "$pipaddr")" "$(json_esc "$pnetmask")" "$(json_esc "$popts")"
    done < "$tmpf"
    rm -f "$tmpf"
    printf '],'

    # Static leases
    printf '"static_leases":['
    static_first=1
    tmpf="/tmp/api_static_leases.tmp"
    uci -X show dhcp 2>/dev/null | grep '=host' > "$tmpf"
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        sname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$sname" ] && continue
        smac=$(uci -q get "dhcp.${sname}.mac" 2>/dev/null || echo "")
        sip=$(uci -q get "dhcp.${sname}.ip" 2>/dev/null || echo "")
        sname_val=$(uci -q get "dhcp.${sname}.name" 2>/dev/null || echo "")
        [ -z "$smac" ] && [ -z "$sip" ] && continue
        [ $static_first -eq 0 ] && printf ","
        static_first=0
        printf '{"section":"%s","mac":"%s","ip":"%s","name":"%s"}' \
            "$(json_esc "$sname")" "$(json_esc "$smac")" "$(json_esc "$sip")" "$(json_esc "$sname_val")"
    done < "$tmpf"
    rm -f "$tmpf"
    printf ']'

    printf '}}'
}

action_edit_dhcp() {
    section=$(get_param "section")
    field=$(get_param "field")
    value=$(get_param "value")

    [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
    [ -z "$field" ] && { printf '{"code":1,"msg":"Field required"}'; return; }

    # Allowed fields
    case "$field" in
        start|limit|leasetime|ignore|force) ;;
        *) printf '{"code":1,"msg":"Invalid field: %s"}' "$(json_esc "$field")"; return ;;
    esac

    if [ "$section" = "dnsmasq" ]; then
        case "$field" in
            domainneeded|boguspriv|localise_queries|rebind_protection|authoritative|allservers|expandhosts|local)
                uci set "dhcp.@dnsmasq[0].${field}=${value}" ;;
            *) printf '{"code":1,"msg":"Invalid dnsmasq field"}'; return ;;
        esac
    else
        exists=$(uci -q get "dhcp.${section}" 2>/dev/null)
        [ -z "$exists" ] && { printf '{"code":1,"msg":"DHCP section not found"}'; return; }
        uci set "dhcp.${section}.${field}=${value}"
    fi

    uci commit dhcp

    # Apply: restart dnsmasq
    /etc/init.d/dnsmasq restart 2>/dev/null &

    printf '{"code":0,"msg":"DHCP setting updated"}'
}

action_edit_dhcp_option() {
    mode=$(get_param "mode")   # add / del
    section=$(get_param "section")
    value=$(get_param "value")

    [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }

    case "$mode" in
        add|del)
            [ -z "$value" ] && { printf '{"code":1,"msg":"Option value required"}'; return; }
            if [ "$mode" = "add" ]; then
                uci add_list "dhcp.${section}.dhcp_option=${value}"
                msg="DHCP option added"
            else
                uci del_list "dhcp.${section}.dhcp_option=${value}" 2>/dev/null
                msg="DHCP option removed"
            fi
            uci commit dhcp
            /etc/init.d/dnsmasq restart 2>/dev/null &
            printf '{"code":0,"msg":"%s"}' "$msg"
            ;;
        clear)
            uci delete "dhcp.${section}.dhcp_option" 2>/dev/null
            uci commit dhcp
            printf '{"code":0,"msg":"DHCP options cleared"}'
            ;;
        *) printf '{"code":1,"msg":"Invalid mode"}'; return ;;
    esac
}

action_edit_static_lease() {
    mode=$(get_param "mode")  # add / edit / delete
    section=$(get_param "section")
    shost=$(get_param "host")   # hostname
    smac=$(get_param "mac")
    sip=$(get_param "ip")

    case "$mode" in
        add)
            [ -z "$smac" ] && { printf '{"code":1,"msg":"MAC address required"}'; return; }
            [ -z "$sip" ] && { printf '{"code":1,"msg":"IP address required"}'; return; }
            # Basic validation
            echo "$smac" | grep -qE '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$' || { printf '{"code":1,"msg":"Invalid MAC format"}'; return; }
            idx=$(uci add dhcp host 2>/dev/null)
            uci set "dhcp.${idx}.mac=${smac}"
            uci set "dhcp.${idx}.ip=${sip}"
            [ -n "$shost" ] && uci set "dhcp.${idx}.name=${shost}"
            uci commit dhcp
            /etc/init.d/dnsmasq restart 2>/dev/null &
            printf '{"code":0,"msg":"Static lease added"}'
            ;;
        edit)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            exists=$(uci -q get "dhcp.${section}" 2>/dev/null)
            [ -z "$exists" ] && { printf '{"code":1,"msg":"Static lease not found"}'; return; }
            [ -n "$smac" ] && uci set "dhcp.${section}.mac=${smac}"
            [ -n "$sip" ] && uci set "dhcp.${section}.ip=${sip}"
            [ -n "$shost" ] && uci set "dhcp.${section}.name=${shost}"
            uci commit dhcp
            /etc/init.d/dnsmasq restart 2>/dev/null &
            printf '{"code":0,"msg":"Static lease updated"}'
            ;;
        delete)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            uci delete "dhcp.${section}" 2>/dev/null
            uci commit dhcp
            /etc/init.d/dnsmasq restart 2>/dev/null &
            printf '{"code":0,"msg":"Static lease deleted"}'
            ;;
        *) printf '{"code":1,"msg":"Invalid mode"}'; return ;;
    esac
}

action_list_dhcp_leases() {
    printf '{"code":0,"data":{"leases":['
    first=1
    leaselist="$leasefile"
    [ -z "$leaselist" ] && leaselist="/tmp/dhcp.leases"
    [ -f "$leaselist" ] && while read -r line; do
        [ -z "$line" ] && continue
        lts=$(echo "$line" | awk '{print $1}')
        lmac=$(echo "$line" | awk '{print $2}')
        lip=$(echo "$line" | awk '{print $3}')
        lhost=$(echo "$line" | awk '{print $4}')
        lclient=$(echo "$line" | awk '{print $5}')
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"ts":"%s","mac":"%s","ip":"%s","host":"%s","client":"%s"}' \
            "$lts" "$(json_esc "$lmac")" "$(json_esc "$lip")" "$(json_esc "$lhost")" "$(json_esc "$lclient")"
    done < "$leaselist"
    printf ']}}'
}

# ---------------------------------------------------------------------------
# FIREWALL RULES & PORT FORWARDS
# ---------------------------------------------------------------------------
action_list_traffic_rules() {
    printf '{"code":0,"data":{"rules":['
    first=1
    tmpf="/tmp/api_fw_rules.tmp"
    uci -X show firewall 2>/dev/null | grep '=rule' > "$tmpf"
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        fname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$fname" ] && continue
        fsrc=$(uci -q get "firewall.${fname}.src" 2>/dev/null || echo "")
        fdest=$(uci -q get "firewall.${fname}.dest" 2>/dev/null || echo "")
        fproto=$(uci -q get "firewall.${fname}.proto" 2>/dev/null || echo "all")
        ftarget=$(uci -q get "firewall.${fname}.target" 2>/dev/null || echo "ACCEPT")
        fname_val=$(uci -q get "firewall.${fname}.name" 2>/dev/null || echo "")
        fsrc_ip=$(uci -q get "firewall.${fname}.src_ip" 2>/dev/null || echo "")
        fdest_ip=$(uci -q get "firewall.${fname}.dest_ip" 2>/dev/null || echo "")
        fsrc_port=$(uci -q get "firewall.${fname}.src_port" 2>/dev/null || echo "")
        fdest_port=$(uci -q get "firewall.${fname}.dest_port" 2>/dev/null || echo "")
        fenabled=$(uci -q get "firewall.${fname}.enabled" 2>/dev/null || echo "1")
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"section":"%s","name":"%s","src":"%s","dest":"%s","proto":"%s","target":"%s","src_ip":"%s","dest_ip":"%s","src_port":"%s","dest_port":"%s","enabled":"%s"}' \
            "$(json_esc "$fname")" "$(json_esc "$fname_val")" "$(json_esc "$fsrc")" "$(json_esc "$fdest")" \
            "$(json_esc "$fproto")" "$(json_esc "$ftarget")" "$(json_esc "$fsrc_ip")" \
            "$(json_esc "$fdest_ip")" "$(json_esc "$fsrc_port")" "$(json_esc "$fdest_port")" "$fenabled"
    done < "$tmpf"
    rm -f "$tmpf"
    printf '],'
    printf '"redirects":['
    first=1
    tmpf="/tmp/api_fw_redir.tmp"
    uci -X show firewall 2>/dev/null | grep '=redirect' > "$tmpf"
    while IFS='=' read -r sec _; do
        [ -z "$sec" ] && continue
        rname=$(echo "$sec" | cut -d'.' -f2)
        [ -z "$rname" ] && continue
        rsrc=$(uci -q get "firewall.${rname}.src" 2>/dev/null || echo "")
        rdest=$(uci -q get "firewall.${rname}.dest" 2>/dev/null || echo "")
        rproto=$(uci -q get "firewall.${rname}.proto" 2>/dev/null || echo "tcp")
        rsrc_dport=$(uci -q get "firewall.${rname}.src_dport" 2>/dev/null || echo "")
        rdest_ip=$(uci -q get "firewall.${rname}.dest_ip" 2>/dev/null || echo "")
        rdest_port=$(uci -q get "firewall.${rname}.dest_port" 2>/dev/null || echo "")
        rname_val=$(uci -q get "firewall.${rname}.name" 2>/dev/null || echo "")
        renabled=$(uci -q get "firewall.${rname}.enabled" 2>/dev/null || echo "1")
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"section":"%s","name":"%s","src":"%s","dest":"%s","proto":"%s","src_dport":"%s","dest_ip":"%s","dest_port":"%s","enabled":"%s"}' \
            "$(json_esc "$rname")" "$(json_esc "$rname_val")" "$(json_esc "$rsrc")" "$(json_esc "$rdest")" \
            "$(json_esc "$rproto")" "$(json_esc "$rsrc_dport")" "$(json_esc "$rdest_ip")" \
            "$(json_esc "$rdest_port")" "$renabled"
    done < "$tmpf"
    rm -f "$tmpf"
    printf ']'
    printf '}}'
}

action_edit_traffic_rule() {
    mode=$(get_param "mode")  # add / edit / delete / toggle
    section=$(get_param "section")

    case "$mode" in
        add)
            fname_val=$(get_param "name")
            fsrc=$(get_param "src")
            fdest=$(get_param "dest")
            fproto=$(get_param "proto")
            ftarget=$(get_param "target")
            fsrc_ip=$(get_param "src_ip")
            fdest_ip=$(get_param "dest_ip")
            fsrc_port=$(get_param "src_port")
            fdest_port=$(get_param "dest_port")

            [ -z "$fsrc" ] && { printf '{"code":1,"msg":"Source zone required"}'; return; }
            [ -z "$ftarget" ] && ftarget="ACCEPT"

            idx=$(uci add firewall rule 2>/dev/null)
            uci set "firewall.${idx}.src=${fsrc}"
            [ -n "$fdest" ] && uci set "firewall.${idx}.dest=${fdest}"
            [ -n "$fproto" ] && [ "$fproto" != "all" ] && uci set "firewall.${idx}.proto=${fproto}"
            uci set "firewall.${idx}.target=${ftarget}"
            [ -n "$fname_val" ] && uci set "firewall.${idx}.name=${fname_val}"
            [ -n "$fsrc_ip" ] && uci set "firewall.${idx}.src_ip=${fsrc_ip}"
            [ -n "$fdest_ip" ] && uci set "firewall.${idx}.dest_ip=${fdest_ip}"
            [ -n "$fsrc_port" ] && uci set "firewall.${idx}.src_port=${fsrc_port}"
            [ -n "$fdest_port" ] && uci set "firewall.${idx}.dest_port=${fdest_port}"
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Traffic rule added"}'
            ;;
        edit)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            exists=$(uci -q get "firewall.${section}" 2>/dev/null)
            [ -z "$exists" ] && { printf '{"code":1,"msg":"Rule not found"}'; return; }
            for f in name src dest proto target src_ip dest_ip src_port dest_port; do
                val=$(get_param "$f")
                [ -n "$val" ] && uci set "firewall.${section}.${f}=${val}"
            done
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Traffic rule updated"}'
            ;;
        delete)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            uci delete "firewall.${section}" 2>/dev/null
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Traffic rule deleted"}'
            ;;
        toggle)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            cur=$(uci -q get "firewall.${section}.enabled" 2>/dev/null || echo "1")
            new=$([ "$cur" = "1" ] && echo "0" || echo "1")
            uci set "firewall.${section}.enabled=${new}"
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Rule %s"}' "$([ "$new" = "1" ] && echo "enabled" || echo "disabled")"
            ;;
        *) printf '{"code":1,"msg":"Invalid mode"}'; return ;;
    esac
}

action_edit_port_forward() {
    mode=$(get_param "mode")  # add / edit / delete / toggle
    section=$(get_param "section")

    case "$mode" in
        add)
            rname_val=$(get_param "name")
            rsrc=$(get_param "src")
            rproto=$(get_param "proto")
            rsrc_dport=$(get_param "src_dport")
            rdest_ip=$(get_param "dest_ip")
            rdest_port=$(get_param "dest_port")

            [ -z "$rsrc" ] && { printf '{"code":1,"msg":"Source zone required"}'; return; }
            [ -z "$rsrc_dport" ] && { printf '{"code":1,"msg":"External port required"}'; return; }
            [ -z "$rdest_ip" ] && { printf '{"code":1,"msg":"Internal IP required"}'; return; }
            [ -z "$rproto" ] && rproto="tcp"

            idx=$(uci add firewall redirect 2>/dev/null)
            uci set "firewall.${idx}.src=${rsrc}"
            uci set "firewall.${idx}.proto=${rproto}"
            uci set "firewall.${idx}.src_dport=${rsrc_dport}"
            uci set "firewall.${idx}.dest_ip=${rdest_ip}"
            [ -n "$rdest_port" ] && uci set "firewall.${idx}.dest_port=${rdest_port}" || uci set "firewall.${idx}.dest_port=${rsrc_dport}"
            [ -n "$rname_val" ] && uci set "firewall.${idx}.name=${rname_val}"
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Port forward added"}'
            ;;
        edit)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            exists=$(uci -q get "firewall.${section}" 2>/dev/null)
            [ -z "$exists" ] && { printf '{"code":1,"msg":"Port forward not found"}'; return; }
            for f in name src proto src_dport dest_ip dest_port; do
                val=$(get_param "$f")
                [ -n "$val" ] && uci set "firewall.${section}.${f}=${val}"
            done
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Port forward updated"}'
            ;;
        delete)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            uci delete "firewall.${section}" 2>/dev/null
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Port forward deleted"}'
            ;;
        toggle)
            [ -z "$section" ] && { printf '{"code":1,"msg":"Section required"}'; return; }
            cur=$(uci -q get "firewall.${section}.enabled" 2>/dev/null || echo "1")
            new=$([ "$cur" = "1" ] && echo "0" || echo "1")
            uci set "firewall.${section}.enabled=${new}"
            uci commit firewall
            fw3 reload 2>/dev/null &
            printf '{"code":0,"msg":"Port forward %s"}' "$([ "$new" = "1" ] && echo "enabled" || echo "disabled")"
            ;;
        *) printf '{"code":1,"msg":"Invalid mode"}'; return ;;
    esac
}

# ---------------------------------------------------------------------------
# ACTIVE CONNECTIONS
# ---------------------------------------------------------------------------
action_list_connections() {
    printf '{"code":0,"data":{"connections":['
    first=1
    # /proc/net/nf_conntrack format:
    # ipv4  2 tcp 6 300 ESTABLISHED src=192.168.1.100 dst=1.2.3.4 sport=12345 dport=443 ...
    # We read up to 500 entries
    conntrack_file=""
    [ -f /proc/net/nf_conntrack ] && conntrack_file="/proc/net/nf_conntrack"
    [ -z "$conntrack_file" ] && [ -f /proc/net/ip_conntrack ] && conntrack_file="/proc/net/ip_conntrack"

    if [ -n "$conntrack_file" ]; then
        count=0
        while read -r line; do
            [ -z "$line" ] && continue
            [ $count -ge 500 ] && break
            count=$((count + 1))

            cproto=$(echo "$line" | awk '{print $2}')
            cstate=$(echo "$line" | awk '{print $5}')
            csrc=$(echo "$line" | sed -n 's/.*src=\([^ ]*\).*/\1/p')
            cdst=$(echo "$line" | sed -n 's/.*dst=\([^ ]*\).*/\1/p')
            csport=$(echo "$line" | sed -n 's/.*sport=\([^ ]*\).*/\1/p')
            cdport=$(echo "$line" | sed -n 's/.*dport=\([^ ]*\).*/\1/p')

            [ $first -eq 0 ] && printf ","
            first=0
            printf '{"proto":"%s","state":"%s","src":"%s","dst":"%s","sport":"%s","dport":"%s"}' \
                "$cproto" "$cstate" "$(json_esc "$csrc")" "$(json_esc "$cdst")" \
                "${csport:-0}" "${cdport:-0}"
        done < "$conntrack_file"
    fi
    printf '],"total":%s}}' "$count"
}

# ---------------------------------------------------------------------------
# SYSTEM CONFIG
# ---------------------------------------------------------------------------
action_system_config() {
    printf '{"code":0,"data":{'

    hostname=$(cat /proc/sys/kernel/hostname 2>/dev/null || echo "")
    tz=$(uci -q get system.@system[0].timezone 2>/dev/null || echo "")
    tzidx=$(uci -q get system.@system[0].timezoneindex 2>/dev/null || echo "")
    ntp_enabled=$(uci -q get system.ntp.enabled 2>/dev/null || echo "0")
    ntp_server=$(uci -q get system.ntp.enable_server 2>/dev/null || echo "0")

    printf '"hostname":"%s",' "$(json_esc "$hostname")"
    printf '"timezone":"%s",' "$(json_esc "$tz")"
    printf '"timezoneindex":"%s",' "$(json_esc "$tzidx")"
    printf '"ntp_enabled":"%s",' "$ntp_enabled"
    printf '"ntp_server":"%s",' "$ntp_server"
    printf '"ntp_servers":['

    first=1
    ntp_tmp="/tmp/api_ntp_$$.tmp"
    uci -q get system.ntp.server 2>/dev/null | tr ' ' '\n' > "$ntp_tmp"
    while read -r srv; do
        [ -z "$srv" ] && continue
        [ $first -eq 0 ] && printf ","
        first=0
        printf '"%s"' "$(json_esc "$srv")"
    done < "$ntp_tmp"
    rm -f "$ntp_tmp"
    printf '],'
    # Current router time
    curtime=$(date "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "")
    printf '"current_time":"%s"' "$(json_esc "$curtime")"
    printf '}}'
}

action_edit_system() {
    field=$(get_param "field")
    value=$(get_param "value")
    [ -z "$field" ] && { printf '{"code":1,"msg":"Field required"}'; return; }

    case "$field" in
        hostname)
            [ -z "$value" ] && { printf '{"code":1,"msg":"Hostname required"}'; return; }
            uci set system.@system[0].hostname="$value"
            echo "$value" > /proc/sys/kernel/hostname 2>/dev/null
            uci commit system
            printf '{"code":0,"msg":"Hostname updated"}'
            ;;
        timezone)
            [ -z "$value" ] && { printf '{"code":1,"msg":"Timezone required"}'; return; }
            uci set system.@system[0].timezone="$value"
            tzidx=$(get_param "tzindex")
            [ -n "$tzidx" ] && uci set system.@system[0].timezoneindex="$tzidx"
            uci commit system
            printf '{"code":0,"msg":"Timezone updated"}'
            ;;
        ntp_enabled)
            uci set system.ntp.enabled="$value"
            uci commit system
            if [ "$value" = "1" ]; then
                /etc/init.d/sysntpd restart 2>/dev/null &
            else
                killall ntpd 2>/dev/null &
            fi
            printf '{"code":0,"msg":"NTP %s"}' "$([ "$value" = "1" ] && echo "enabled" || echo "disabled")"
            ;;
        ntp_server)
            [ -z "$value" ] && { printf '{"code":1,"msg":"NTP server required"}'; return; }
            mode=$(get_param "mode")  # add / del
            case "$mode" in
                add) uci add_list "system.ntp.server=$value" ;;
                del) uci del_list "system.ntp.server=$value" 2>/dev/null ;;
                *) printf '{"code":1,"msg":"Mode required (add/del)"}'; return ;;
            esac
            uci commit system
            /etc/init.d/sysntpd restart 2>/dev/null &
            printf '{"code":0,"msg":"NTP server updated"}'
            ;;
        ntp_enable_server)
            uci set system.ntp.enable_server="$value"
            uci commit system
            printf '{"code":0,"msg":"NTP server %s"}' "$([ "$value" = "1" ] && echo "enabled" || echo "disabled")"
            ;;
        *) printf '{"code":1,"msg":"Invalid field"}'; return ;;
    esac
}

# ---------------------------------------------------------------------------
# DIAGNOSTICS
# ---------------------------------------------------------------------------
action_diag_ping() {
    host=$(get_param "host")
    count=$(get_param "count")
    [ -z "$host" ] && { printf '{"code":1,"msg":"Host required"}'; return; }
    # Sanitize: only allow valid hostname/IP chars
    case "$host" in *[^a-zA-Z0-9.:_-]*) printf '{"code":1,"msg":"Invalid host"}'; return ;; esac
    [ -z "$count" ] && count=4
    case "$count" in ''|*[!0-9]*) count=4 ;; esac
    [ "$count" -gt 50 ] && count=50

    printf '{"code":0,"data":{"output":"'
    ping -c "$count" -W 3 "$host" 2>/dev/null | while read -r line; do
        printf '%s\\n' "$(json_esc "$line")"
    done
    printf '"}}'
}

action_diag_traceroute() {
    host=$(get_param "host")
    [ -z "$host" ] && { printf '{"code":1,"msg":"Host required"}'; return; }
    case "$host" in *[^a-zA-Z0-9.:_-]*) printf '{"code":1,"msg":"Invalid host"}'; return ;; esac

    printf '{"code":0,"data":{"output":"'
    traceroute -m 15 -w 3 "$host" 2>/dev/null | while read -r line; do
        printf '%s\\n' "$(json_esc "$line")"
    done
    printf '"}}'
}

action_diag_nslookup() {
    host=$(get_param "host")
    [ -z "$host" ] && { printf '{"code":1,"msg":"Host required"}'; return; }
    case "$host" in *[^a-zA-Z0-9.:_-]*) printf '{"code":1,"msg":"Invalid host"}'; return ;; esac

    printf '{"code":0,"data":{"output":"'
    nslookup "$host" 2>/dev/null | while read -r line; do
        printf '%s\\n' "$(json_esc "$line")"
    done
    printf '"}}'
}

# ---------------------------------------------------------------------------
# REBOOT
# ---------------------------------------------------------------------------
action_reboot() {
    printf '{"code":0,"msg":"Rebooting..."}'
    # Flush output before reboot
    sleep 1
    reboot 2>/dev/null || /sbin/reboot 2>/dev/null || true
}

# -- Xiaomi Services ------------------------------------------------
# Known init scripts (name:display label)
SERVICES="tbusd:tbusd
trafficd:trafficd
miio_client:MiIO Client
miot:MiOT LED
xqbc:XQBC
xq_info_sync_mqtt:XQ Info Sync
messagingagent.sh:Messaging Agent
mosquitto:MQTT Broker
smartcontroller:Smart Controller
cab_meshd:CAP Mesh Daemon
xiaoqiang_sync:XiaoQiang Sync
milog:MiLog
miwifi-discovery:MiWiFi Discovery
netapi:Net API"

action_services() {
    svc_action=$(get_param "service_action")
    svc_name=$(get_param "service_name")

    if [ -n "$svc_action" ] && [ -n "$svc_name" ]; then
        if [ -f "/etc/init.d/${svc_name}" ]; then
            case "$svc_action" in
                start)
                    /etc/init.d/${svc_name} start 2>/dev/null
                    printf '{"code":0,"msg":"started %s"}' "$svc_name"
                    ;;
                stop)
                    /etc/init.d/${svc_name} stop 2>/dev/null
                    printf '{"code":0,"msg":"stopped %s"}' "$svc_name"
                    ;;
                restart)
                    /etc/init.d/${svc_name} restart 2>/dev/null
                    printf '{"code":0,"msg":"restarted %s"}' "$svc_name"
                    ;;
                enable)
                    # Remove from persistent disabled list
                    touch /data/dashboard/.disabled_services 2>/dev/null
                    grep -v "^${svc_name}$" /data/dashboard/.disabled_services > /tmp/.ds_tmp 2>/dev/null
                    cat /tmp/.ds_tmp 2>/dev/null > /data/dashboard/.disabled_services
                    rm -f /tmp/.ds_tmp
                    printf '{"code":0,"msg":"enabled %s at boot"}' "$svc_name"
                    ;;
                disable)
                    # Add to persistent disabled list + stop now
                    touch /data/dashboard/.disabled_services 2>/dev/null
                    grep -q "^${svc_name}$" /data/dashboard/.disabled_services 2>/dev/null || \
                        echo "$svc_name" >> /data/dashboard/.disabled_services
                    # Stop the service now
                    /etc/init.d/${svc_name} stop 2>/dev/null
                    printf '{"code":0,"msg":"disabled %s at boot"}' "$svc_name"
                    ;;
                *)
                    printf '{"code":1,"msg":"Unknown action: %s"}' "$svc_action"
                    ;;
            esac
        else
            printf '{"code":1,"msg":"Service %s not found"}' "$svc_name"
        fi
        return
    fi

    # Build disabled list for fast lookup
    DISABLED_TMP=$(mktemp -t ds_XXXXXX 2>/dev/null || echo "/tmp/ds_$$")
    > "$DISABLED_TMP"
    [ -f /data/dashboard/.disabled_services ] && cat /data/dashboard/.disabled_services > "$DISABLED_TMP"

    printf '{"code":0,"data":{"services":['
    local first=1
    echo "$SERVICES" | while IFS=':' read -r iname label; do
        [ -z "$iname" ] && continue
        local running=0 rss="0"
        local pids=""
        pids=$(pidof "$iname" 2>/dev/null)
        if [ -n "$pids" ]; then
            running=1
            local total_rss=0 count=0
            for p in $pids; do
                local prss
                prss=$(grep "^VmRSS:" /proc/$p/status 2>/dev/null | awk '{print $2}')
                [ -z "$prss" ] && prss=0
                total_rss=$((total_rss + prss))
                count=$((count + 1))
            done
            [ "$count" -gt 0 ] && rss=$((total_rss / count))
        else
            local pcount
            pcount=$(ps 2>/dev/null | grep -v grep | grep "$iname" | wc -l)
            [ "$pcount" -gt 0 ] && running=1
        fi
        local enabled=1
        grep -q "^${iname}$" "$DISABLED_TMP" 2>/dev/null && enabled=0
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"name":"%s","label":"%s","running":%d,"rss":%s,"enabled":%d}' \
            "$(json_esc "$iname")" "$(json_esc "$label")" "$running" "$rss" "$enabled"
    done
    rm -f "$DISABLED_TMP"
    printf ']}}'
}



# -- Bloat Crons ----------------------------------------------------
BLOAT_CRONS="sp_check.sh:*/5 * * * * command -v sp_check.sh >/dev/null && sp_check.sh
startscene_crontab.lua:* * * * * /usr/sbin/startscene_crontab.lua \x60/bin/date \"+%u %H:%M\"\x60
otapredownload:1 3,4,5 * * * /usr/sbin/otapredownload >/dev/null 2>&1
mobile_accel.sh:*/3 * * * * /usr/sbin/mobile_accel.sh check >/dev/null 2>&1"

action_list_bloat_crons() {
    printf '{"code":0,"data":{"crons":['
    local first=1
    echo "$BLOAT_CRONS" | while IFS=':' read -r name line; do
        [ -z "$name" ] && continue
        local active=0
        grep -qF "$line" /etc/crontabs/root 2>/dev/null && active=1
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"name":"%s","active":%d}' "$(json_esc "$name")" $active
    done
    printf ']}}'
}

action_toggle_bloat_cron() {
    name=$(get_param "name")
    act=$(get_param "toggle_action")  # remove or restore
    [ -z "$name" ] && { printf '{"code":1,"msg":"Cron name required"}'; return; }
    [ -z "$act" ] && { printf '{"code":1,"msg":"Action required"}'; return; }

    # Find the line for this cron
    line=$(echo "$BLOAT_CRONS" | tr ':' '\n' | while read -r n; do
        read -r l
        [ "$n" = "$name" ] && echo "$l" && break
    done)
    [ -z "$line" ] && { printf '{"code":1,"msg":"Unknown cron: %s"}' "$(json_esc "$name")"; return; }

    # Build a pattern that matches the cron line (escape for grep -v)
    # Use a distinctive part of the line that's unique
    case "$act" in
        remove)
            cp /etc/crontabs/root /etc/crontabs/root.bak 2>/dev/null
            grep -vF "$line" /etc/crontabs/root > /tmp/crontab_new
            mv /tmp/crontab_new /etc/crontabs/root
            /etc/init.d/cron restart 2>/dev/null
            printf '{"code":0,"msg":"Removed %s"}' "$(json_esc "$name")"
            ;;
        restore)
            grep -qF "$line" /etc/crontabs/root 2>/dev/null && {
                printf '{"code":0,"msg":"%s already active"}' "$(json_esc "$name")"
                return
            }
            echo "$line" >> /etc/crontabs/root
            /etc/init.d/cron restart 2>/dev/null
            printf '{"code":0,"msg":"Restored %s"}' "$(json_esc "$name")"
            ;;
        *) printf '{"code":1,"msg":"Invalid action: %s"}' "$(json_esc "$act")" ;;
    esac
}

# -- Tracker Domain Blocking -----------------------------------------
# Domains sourced from /etc/config/miwifi + common Xiaomi endpoints
KNOWN_DOMAINS="api.miwifi.com:API
log.miwifi.com:Log
s.miwifi.com:Stats
app.miwifi.com:App
stun.miwifi.com:STUN
broker.miwifi.com:MQTT Broker
bbs.xiaomi.cn:Forums
router.miwifi.com:Router Mgmt"

BLOCKLIST="/data/dashboard/.blocked_domains"
DNSMASQ_BLOCK="/etc/dnsmasq.d/xiaomi-block.conf"

action_list_blocked_domains() {
    printf '{"code":0,"data":{"domains":['
    local first=1
    echo "$KNOWN_DOMAINS" | while IFS=':' read -r domain label; do
        [ -z "$domain" ] && continue
        local blocked=0
        grep -q "^${domain}$" "$BLOCKLIST" 2>/dev/null && blocked=1
        [ $first -eq 0 ] && printf ","
        first=0
        printf '{"domain":"%s","label":"%s","blocked":%d}' "$(json_esc "$domain")" "$(json_esc "$label")" $blocked
    done
    printf ']}}'
}

action_toggle_domain_block() {
    domain=$(get_param "domain")
    act=$(get_param "toggle_action")  # block or unblock
    [ -z "$domain" ] && { printf '{"code":1,"msg":"Domain required"}'; return; }
    [ -z "$act" ] && { printf '{"code":1,"msg":"Action required"}'; return; }

    # Validate domain is in known list
    valid=0
    echo "$KNOWN_DOMAINS" | while IFS=':' read -r d _; do
        [ "$d" = "$domain" ] && echo "1" > /tmp/_domain_valid
    done
    [ -f /tmp/_domain_valid ] && valid=$(cat /tmp/_domain_valid) && rm -f /tmp/_domain_valid
    [ "$valid" != "1" ] && { printf '{"code":1,"msg":"Unknown domain"}'; return; }

    touch "$BLOCKLIST" 2>/dev/null

    case "$act" in
        block)
            grep -q "^${domain}$" "$BLOCKLIST" 2>/dev/null || echo "$domain" >> "$BLOCKLIST"
            ;;
        unblock)
            grep -v "^${domain}$" "$BLOCKLIST" > /tmp/_blocklist_new 2>/dev/null
            cat /tmp/_blocklist_new > "$BLOCKLIST"
            rm -f /tmp/_blocklist_new
            ;;
        *) printf '{"code":1,"msg":"Invalid action"}'; return ;;
    esac

    # Regenerate dnsmasq block conf
    apply_domain_blocks

    printf '{"code":0,"msg":"%s %s"}' "$(json_esc "$domain")" "$([ "$act" = "block" ] && echo "blocked" || echo "unblocked")"
}

apply_domain_blocks() {
    > "$DNSMASQ_BLOCK"
    if [ -f "$BLOCKLIST" ] && [ -s "$BLOCKLIST" ]; then
        while read -r d; do
            [ -z "$d" ] && continue
            echo "address=/${d}/0.0.0.0" >> "$DNSMASQ_BLOCK"
        done < "$BLOCKLIST"
    fi
    /etc/init.d/dnsmasq restart 2>/dev/null &
}

# -- Stat Points Cleanup ---------------------------------------------
action_stat_points_info() {
    local dir="/tmp/stat_points"
    local size=0 count=0
    if [ -d "$dir" ]; then
        size=$(du -s "$dir" 2>/dev/null | awk '{print $1}')
        count=$(find "$dir" -type f 2>/dev/null | wc -l)
    fi
    printf '{"code":0,"data":{"size_kb":%s,"file_count":%s,"exists":%d}}' \
        "${size:-0}" "${count:-0}" "$([ -d "$dir" ] && echo 1 || echo 0)"
}

action_clear_stat_points() {
    local dir="/tmp/stat_points"
    if [ -d "$dir" ]; then
        rm -rf "$dir"/* 2>/dev/null
        printf '{"code":0,"msg":"Stat points cleared"}'
    else
        printf '{"code":0,"msg":"Nothing to clear"}'
    fi
}


# ---------------------------------------------------------------------------
# DISPATCH
# ---------------------------------------------------------------------------
action=$(get_param "action")

case "$action" in
    overview)        action_overview ;;
    routing)         action_routing ;;
    firewall)        action_firewall ;;
    syslog)          action_syslog ;;
    processes)       action_processes ;;
    ps_mem)          action_ps_mem ;;
    list_ifaces)     action_list_ifaces ;;
    edit_iface)      action_edit_iface ;;
    create_iface)    action_create_iface ;;
    delete_iface)    action_delete_iface ;;
    list_devices)    action_list_devices ;;
    create_device)   action_create_device ;;
    delete_device)   action_delete_device ;;
    list_wireless)   action_list_wireless ;;
    edit_wifi_iface) action_edit_wifi_iface ;;
    create_wifi_vap) action_create_wifi_vap ;;
    delete_wifi_vap) action_delete_wifi_vap ;;
    dhcp_config)     action_dhcp_config ;;
    edit_dhcp)        action_edit_dhcp ;;
    edit_dhcp_option)  action_edit_dhcp_option ;;
    edit_static_lease) action_edit_static_lease ;;
    list_dhcp_leases) action_list_dhcp_leases ;;
    list_traffic_rules) action_list_traffic_rules ;;
    edit_traffic_rule)  action_edit_traffic_rule ;;
    edit_port_forward)  action_edit_port_forward ;;
    list_connections)   action_list_connections ;;
    system_config)     action_system_config ;;
    edit_system)       action_edit_system ;;
    diag_ping)         action_diag_ping ;;
    diag_traceroute)   action_diag_traceroute ;;
    diag_nslookup)     action_diag_nslookup ;;
    reboot)            action_reboot ;;
    services)                action_services ;;
    list_bloat_crons)        action_list_bloat_crons ;;
    toggle_bloat_cron)       action_toggle_bloat_cron ;;
    list_blocked_domains)    action_list_blocked_domains ;;
    toggle_domain_block)     action_toggle_domain_block ;;
    stat_points_info)        action_stat_points_info ;;
    clear_stat_points)       action_clear_stat_points ;;
    *)               printf '{"code":1,"msg":"Unknown action: %s"}' "$action" ;;
esac
