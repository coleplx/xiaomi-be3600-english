# Extracted from api.cgi — these are pure functions with no router dependencies.

get_param() {
    local key="$1"
    local val
    val=$(echo "$QS" | sed -n "s/.*[?&]${key}=\([^&]*\).*/\1/p")
    [ -z "$val" ] && val=$(echo "$QS" | sed -n "s/^${key}=\([^&]*\).*/\1/p")
    printf '%b' "${val//%/\\x}" | sed 's/+/ /g'
}

json_esc() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\n/\\n/g'
}

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

fmt_size() {
    local kb="$1" val
    if [ "$kb" -gt 1048576 ]; then
        val=$(echo "scale=1; $kb / 1048576" | bc 2>/dev/null)
        [ -n "$val" ] && printf "%.1f GB" "$val" || echo "? GB"
    elif [ "$kb" -gt 1024 ]; then
        val=$(echo "scale=1; $kb / 1024" | bc 2>/dev/null)
        [ -n "$val" ] && printf "%.1f MB" "$val" || echo "? MB"
    else
        printf "%d KB" "$kb"
    fi
}
