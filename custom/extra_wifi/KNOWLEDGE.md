# Xiaomi BE3600 Router — Technical Knowledge Base
# Last updated: 2026-05-11 (session 2: VLAN, dual-band, VAP recovery)

## Hardware
- Xiaomi BE3600 (RD15, model_number=0002)
- Dual-band: wifi0 (2.4GHz 802.11bgn/ax/be) + wifi1 (5GHz 802.11abn/ac/ax/be)
- Qualcomm qcawificfg80211 wireless driver
- 4 physical ports: 1,2,3 (1G, eth0.X) + 4 (2.5G, eth1)
  - eth0 = internal switch, each port on its own VLAN (vid 1,2,3)
  - eth1 = direct PHY (2.5G WAN/LAN uplink)
- UBIFS /data/ partition (persistent, writable)
- squashfs root filesystem (read-only)

## Software Stack
- OpenWrt derivative ("XiaoQiang" / MiWiFi)
- BusyBox ash shell (no xxd, no od, no file, no httpd)
- Lua 5.1.5 (double int32, security patched)
- Nginx main web server (port 80/443) + fcgi-cgi backend on port 8920
- uhttpd available (port 8090 for custom panel)
- LuCI web framework (Xiaomi-modified, ALL .lua are bytecode-compiled)
- hostapd (Qualcomm fork) manages APs, uses per-VAP config at /var/run/hostapd-wl*.conf
- wpa_cli / hostapd_cli available

## Key Paths
| Path | Description |
|------|-------------|
| /etc/config/wireless | UCI WiFi config |
| /etc/config/network | UCI network config (includes switch_vlan) |
| /etc/config/dhcp | UCI DHCP config |
| /etc/config/firewall | UCI firewall zones/rules |
| /var/run/hostapd-wl*.conf | Generated hostapd per-VAP configs |
| /var/run/hostapd/global | hostapd global control socket |
| /var/run/hostapd-wifi0/ | hostapd per-radio control sockets (wl1, wl13, wl4) |
| /var/run/hostapd-wifi1/ | hostapd per-radio control sockets (wl0, wl5) |
| /var/run/wifi.lock | Global wifi operation lock (DO NOT USE) |
| /var/run/extra_wifi_uhttpd.pid | PID of custom uhttpd |
| /data/extra_wifi/ | Custom panel files (persistent) |
| /data/lang_patch/ | Language patch overlay (bind-mounted) |
| /lib/wifi/qcawificfg80211.sh | Qualcomm WiFi driver script |

## LuCI Architecture
- ALL controller .lua files are COMPILED BYTECODE (magic 0x1B)
- Cannot add plain-text Lua controllers — dispatcher ignores them
- URL format: /cgi-bin/luci/;stok=SESSION_TOKEN/path/to/page
- Session tokens validated by LuCI; requests without token = 500 error

## WiFi System Architecture

### UCI Wireless Config Structure
- wifi-device sections: wifi0 (2.4G), wifi1 (5G)
  - type='qcawificfg80211', channel='auto', htmode='HT40'|'HT80'
  - hwmode='11beg'|'11bea'
- wifi-iface sections: VAP definitions
  - Named: miot_2G, bh_ap_2g, bh_ap_5g (reserved, never touch)
  - Anonymous [0]=2.4G main, [1]=5G main (bsd='1' = band steering)
  - Our tag: extra_wifi='1' + extra_wifi_group='<ssid>' (for dual-band grouping)
  - Key options: device, ifname, ssid, encryption, key, network, mode

### VAP Naming Quirks ("Cursed" Names)
- wl0, wl1 = main VAPs (always present)
- wl03, wl04, wl16 etc = names that FAIL with "Could not configure driver mode"
- Root cause: Qualcomm driver caches deleted VAP names internally
- Fix: start from suffix 10 (wl10, wl11...) to avoid recently-deleted names
- wl naming: wl0/wl0X on wifi1 (5G), wl1/wl1X on wifi0 (2.4G)

### Critical: wifi reload PILE-UP
- `wifi reload` takes 30-60+ seconds, uses lock at /var/run/wifi.lock
- Multiple calls pile up waiting for lock, can CRASH entire WiFi
- NEVER call from CGI. Use apply_vap.sh (iw + hostapd, zero lock)

### VAP Management (apply_vap.sh)
- Config generated FROM SCRATCH (no template dependency!)
- 5GHz: hw_mode=a, channel=36 (non-DFS, safe)
- 2.4GHz: hw_mode=g, channel=auto
- Required for client association: noauth_pasn_activated=1, owe_ptk_workaround=1
- These are Qualcomm driver requirements, not security changes
- Verify VAP up with `iw dev $ifname info | grep "ssid $ssid"`
- If hostapd fails: clean up VAP, do NOT set ifname in UCI

### hostapd Config Generation Pitfalls
- sed "s/interface=.*/.../" also matches ctrl_interface= → CORRUPTS config
- Fix: use ^ anchor: sed "s/^interface=.*/interface=..."
- Template files (/var/run/hostapd-wl0.conf) can be deleted by aggressive cleanup
- Generate config from scratch instead of copying templates
- bridge= in hostapd must match the VLAN bridge (br-lan or br-vlan_X)

## VLAN Architecture (AP Mode)

### Traffic Flow
```
WiFi Client → wlXX → br-vlan_N → eth1.N (tagged) → Port 4 (2.5G) → upstream router
```

### VLAN Creation Steps
1. UCI: `config interface 'vlan_N'` with ifname='eth1.N', type='bridge', proto='none'
2. UCI: `config switch_vlan 'vlanN'` with device='switch1', vlan='N', vid='N', ports='5t'
3. Runtime: `ip link add link eth1 name eth1.N type vlan id N`
4. Runtime: `brctl addbr br-vlan_N` + add eth1.N + VAP
5. WiFi: set wifi-iface option network='vlan_N'

### Port Layout
- eth0 = internal switch (ports 1-3, each with own VLAN 1/2/3)
- eth1 = direct 2.5G PHY (port 4) — THIS is the VLAN trunk uplink
- switch_vlan only needed for eth0 (internal switch). eth1 VLANs work without switch config
- For WiFi VLAN in AP mode: MUST use eth1.N (port 4), not eth0.N

## UCI Section Renaming
- When a wifi-iface section is deleted, remaining sections get RENAMED
- Internal names (cfgXXXXXXXX) are NOT stable — use extra_wifi tag + SSID fallback

## Shell/CGI Pitfalls
1. sshpass quoting: single quotes in double-quoted variables become literal chars
2. ash pipe subshells: `while read` in pipeline loses variable changes → use temp files
3. `uci add` prints section name to stdout → pollutes CGI JSON → capture with $()
4. `$()` capture hangs if background processes keep stdout open → redirect >/dev/null 2>&1 &
5. `uci -X show` = real names, `uci show` = index names (shift on delete)
6. `local` in ash: `local a b` ok, `local a=1 b=2` ok, but avoid in pipe subshells
7. `grep "extra_wifi='1'"` — note the quotes around value in uci show output
8. `sed -i` on busybox: use double quotes for variables, single for literals

## Custom Panel Architecture (port 8090)
- uhttpd on port 8090 serving from /data/extra_wifi/www/
- CGI: /data/extra_wifi/www/cgi-bin/extra_wifi.cgi
- Backend scripts: apply_vap.sh, boot_setup.sh
- Persistence: firewall include (boot_setup.sh on every boot) + cron 2min fallback
- Boot recovery: wait 30s for radios → scan extra_wifi UCI → call apply_vap.sh for each
- Deploy: custom/extra_wifi/deploy.sh

## Panel Features
- Create: single-band (2.4G/5G) or dual-band (both radios, same SSID)
- VLAN: optional VLAN ID field → auto-creates eth1.N + bridge + switch_vlan
- List: groups dual-band by SSID, shows VLAN ID
- Delete: removes UCI + VAP + hostapd, SSID-based fallback for stable lookup
- All changes applied instantly via apply_vap.sh (no wifi lock)

## System Utilities
- uci, iw, iwinfo, iwconfig, ifconfig, brctl, ip
- wpa_cli, hostapd_cli
- luac (Lua bytecode compiler)
- uhttpd, nginx, fcgi-cgi, spawn-fcgi
- wifi, wifi reload (DO NOT USE FROM CGI — WILL CRASH WIFI)
