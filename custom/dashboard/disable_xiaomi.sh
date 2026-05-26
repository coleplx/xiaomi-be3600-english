#!/bin/sh
# disable_xiaomi.sh - Stop Xiaomi services marked as disabled
# Reads /data/dashboard/.disabled_services (one name per line) and stops each.
# Idempotent: safe to run repeatedly.

CONFIG="/data/dashboard/.disabled_services"

[ -f "$CONFIG" ] || exit 0

while read -r svc; do
    [ -z "$svc" ] && continue
    [ -f "/etc/init.d/$svc" ] || continue
    /etc/init.d/"$svc" stop 2>/dev/null
done < "$CONFIG"
