#!/bin/sh
# disable_xiaomi.sh - Stop Xiaomi services + apply domain blocking
# Reads /data/dashboard/.disabled_services and /data/dashboard/.blocked_domains
# Idempotent: safe to run repeatedly.

CONFIG="/data/dashboard/.disabled_services"
BLOCKLIST="/data/dashboard/.blocked_domains"
DNSMASQ_BLOCK="/etc/dnsmasq.d/xiaomi-block.conf"

# ── Stop disabled services ──
if [ -f "$CONFIG" ]; then
    while read -r svc; do
        [ -z "$svc" ] && continue
        [ -f "/etc/init.d/$svc" ] || continue
        /etc/init.d/"$svc" stop 2>/dev/null
    done < "$CONFIG"
fi

# ── Apply domain blocking ──
# Regenerate dnsmasq block conf from persistent blocklist.
# Only restart dnsmasq if the file actually changed.
NEED_RESTART=0
TMP_BLOCK="/tmp/_xiaomi_block.tmp"

if [ -f "$BLOCKLIST" ] && [ -s "$BLOCKLIST" ]; then
    > "$TMP_BLOCK"
    while read -r domain; do
        [ -z "$domain" ] && continue
        echo "address=/${domain}/0.0.0.0" >> "$TMP_BLOCK"
    done < "$BLOCKLIST"
    if ! cmp -s "$TMP_BLOCK" "$DNSMASQ_BLOCK" 2>/dev/null; then
        cp "$TMP_BLOCK" "$DNSMASQ_BLOCK"
        NEED_RESTART=1
    fi
    rm -f "$TMP_BLOCK"
else
    # No blocklist — remove conf if it exists
    if [ -f "$DNSMASQ_BLOCK" ]; then
        rm -f "$DNSMASQ_BLOCK"
        NEED_RESTART=1
    fi
fi

[ "$NEED_RESTART" = "1" ] && /etc/init.d/dnsmasq restart 2>/dev/null &
