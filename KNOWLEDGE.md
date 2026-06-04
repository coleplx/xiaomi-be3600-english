# Xiaomi BE3600 Router — Technical Knowledge Base
# Last updated: 2026-06-03 (factory reset verification, test framework, apply_vap fixes)

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

### VAP Naming
- Factory ifnames (stable across reboots, verified 2026-06-03):
  - wifi0 (2.4G): wl1 (main), wl4 (backhaul), wl13 (miot)
  - wifi1 (5G): wl0 (main), wl5 (backhaul)
- wl naming convention: wifi0 → wl1, wl1X (suffixes 0-9); wifi1 → wl0, wl0X (suffixes 0-9)
- `type ap` (single underscore) FAILS — requires management daemon
- `type __ap` (double underscore) WORKS — Qualcomm driver requirement
- `iw dev del` works even while hostapd is running — safe cleanup
- "Cursed" name issue (previously documented) was likely caused by `type ap` vs `type __ap` confusion. With `__ap`, suffix 00 works fine (verified).
- apply_vap.sh iterates suffixes 10-30: wl10-wl19 for wifi0, wl00-wl09 for wifi1

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

## VLAN Architecture (AP Mode) — Verified 2026-06-03

### Traffic Flow
```
WiFi Client → wlXX → br-vlan_N → eth1.N (tagged) → Port 4 (2.5G) → upstream router
```

### VLAN Creation Steps
1. Runtime: `ip link add link eth1 name eth1.N type vlan id N` (creates tagged subinterface)
2. Runtime: `brctl addbr br-vlan_N` (creates bridge — hostapd will auto-create if missing)
3. Runtime: `brctl addif br-vlan_N eth1.N` (add VLAN subinterface to bridge)
4. Create VAP with `bridge=br-vlan_N` in hostapd config
5. Optionally: `brctl addif br-vlan_N wlXX` if VAP was created before bridge

### Verified VLAN Behavior
- **hostapd auto-creates bridges**: If config has `bridge=br-vlan_N` and the bridge doesn't exist, hostapd creates it automatically and adds the VAP interface. The bridge will exist but have no uplink (eth1.N) — VAP is isolated until you add it.
- **Late bridge addition**: You can `brctl addif br-vlan_N wlXX` after both VAP and bridge exist — no restart needed, traffic flows immediately.
- **Multiple VAPs on same bridge**: Multiple VAPs (2G + 5G) can share one VLAN bridge. Both appear as bridge members.
- **Different VLANs coexist**: VAPs on br-vlan_100 and br-vlan_101 work simultaneously without interference.
- **VAP deletion**: `iw dev wlXX del` removes the interface from any bridge automatically.

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

---

## CRITICAL: Filesystem Reality

**`/etc/config` is on `/dev/mapper/sec_cfg` (ext4, persistent)** — NOT tmpfs. UCI changes (`uci commit`) survive reboots. This applies to `/etc/config/wireless`, `/etc/config/network`, etc.

**`/etc/init.d/` and `/etc/rc.d/` ARE tmpfs** — init script and symlink changes do NOT survive reboots.

**`/data/` is UBIFS** — persistent. Dashboard files live here.

**`/var/run/` is tmpfs** — cleared on every reboot.

## CRITICAL: Router SSH and Deployment

**SSH command:**
```
sshpass -p 'root' ssh -oHostKeyAlgorithms=+ssh-rsa -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@<ip>
```

**scp with sshpass WORKS with the -O flag.** Use this for file uploads:
```
sshpass -p 'root' scp -O -oHostKeyAlgorithms=+ssh-rsa -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null <file> root@<ip>:<dest>
```
The `-O` flag forces the legacy SCP protocol (required for this router's dropbear).

**Base64-over-SSH breaks on large files** (80KB+). Never use `echo $B64 | base64 -d` over SSH for files larger than ~10KB.

**deploy.sh ROUTER_IP**: The script sources `.env` AFTER setting the default. The `.env` file always wins. Always check `.env` first.

**Router uses static IP** (set via UCI network.lan.ipaddr). Factory default: 192.168.31.1. The IP in `.env` reflects whatever was configured by the user. Check `.env` or `ip neigh` to find current IP.

## CRITICAL: global hostapd vs apply_vap.sh Architecture

There are TWO hostapd processes that can manage VAPs:

1. **Global Qualcomm hostapd** (`hostapd -g /var/run/hostapd/global`): Single process managing ALL VAPs defined in `/etc/config/wireless`. Generates configs with Xiaomi WPS fields (manufacturer=xiaomi, device_name=XiaoMiRouter, wps_state, uuid, etc.). Uses per-radio control sockets at `/var/run/hostapd-wifi0/` and `/var/run/hostapd-wifi1/`.

2. **apply_vap.sh hostapd** (separate `hostapd -B` per VAP): Started by dashboard create/edit. Generates MINIMAL configs (no WPS, no Xiaomi branding). Each VAP gets its own hostapd process.

**Runtime behavior (verified 2026-06-03):**
- At BOOT: Only the global hostapd runs. It reads ALL UCI wifi-iface sections and generates configs + creates interfaces for each non-disabled VAP. UCI ifnames are PRESERVED across reboots (no reassignment).
- UCI-only VAP creation (no manual iw/hostapd): Works — VAP appears after next reboot. The global hostapd auto-generates config with Xiaomi WPS fields injected.
- At RUNTIME: The global hostapd does NOT pick up new interfaces created by apply_vap.sh. A VAP created with `iw dev wifi1 interface add wl00 type __ap` without hostapd has NO SSID (invisible).
- Dual ownership: If both global and per-VAP hostapd manage the same interface, they coexist in the same ctrl_interface directory. The per-VAP hostapd handles the VAP's radio; the global hostapd just has a socket for it. This does NOT cause corruption.
- /var/run/hostapd-*.conf files are REGENERATED at each boot by the Qualcomm scripts — not persisted across reboots.

**Boot recovery flow:**
1. Global hostapd starts → creates all UCI-defined VAPs with Xiaomi WPS
2. boot_setup.sh bind-mounts patched wifi scripts (if available)
3. boot_setup.sh scans for extra_wifi=1 VAPs and verifies they're up
4. Health checks periodically strip Xiaomi WPS from configs and re-apply

## CRITICAL: Xiaomi WPS Branding

Phones detect Xiaomi routers via WPS Information Elements in beacon frames:
- `manufacturer=xiaomi`
- `device_name=XiaoMiRouter`
- `model_name=RD15`

These are added by the global Qualcomm hostapd to ALL VAP configs it manages. apply_vap.sh configs do NOT include them.

To remove Xiaomi branding from a VAP: strip `manufacturer`, `device_name`, `model_name` lines from `/var/run/hostapd-<ifname>.conf` and restart the VAP with a clean config via apply_vap.sh.

## CRITICAL: VAP Naming and Persistence

The Qualcomm driver assigns ifnames as `wl<radioidx><suffix>`:
- wifi0 (2.4GHz): wl1, wl11, wl12, wl13...
- wifi1 (5GHz): wl0, wl01, wl02, wl03...

**UCI ifnames are STABLE across reboots (verified 2026-06-03).** Three reboot cycles showed zero ifname rotation. User-assigned ifnames (wl00) persisted through reboots and were correctly picked up by the global hostapd. The previously documented "ifname overwrite" behavior was not observed on factory firmware.

**miot_2G (ifname=wl13)** is Xiaomi's IoT VAP (hidden, open, isolated). It is ACTIVE on factory firmware. apply_vap.sh's ifname_collision() correctly detects wl13 as claimed by miot_2G in UCI and skips it. Do NOT use wl13 for user VAPs.

## Utilities Available

- All standard router commands present: uci, iw, iwinfo, iwconfig, ifconfig, brctl, ip, iptables, hostapd, uhttpd, wpa_cli, hostapd_cli, killall, netstat
- `ps` format: PID USER VSZ STAT COMMAND (BusyBox)
- `bc` is MISSING — fmt_size() in api.cgi falls back to `? GB`/`? MB` for converted sizes
- `/etc/xiaoqiang_version` exists but is EMPTY on factory firmware — fw version falls through to "Unknown"
- `uci add wireless wifi-iface` returns section names like `cfg0b3579`

## Test Framework

- **bats** (Bash Automated Testing System) for unit tests
- Installed via `apt install bats` or `git clone https://github.com/bats-core/bats-core.git`
- Directory structure:
  ```
  tests/
  ├── helpers.bash          — shared utilities (common_setup/teardown)
  ├── fixtures/             — extracted helper functions for isolation
  │   ├── api_helpers.sh    — get_param, json_esc, fmt_uptime, fmt_size
  │   └── apply_vap_helpers.sh — resolve_bridge, gen_config_minimal
  └── unit/                 — pure logic tests (no router required)
      ├── api_helpers.bats  — 20 tests
      └── apply_vap.bats    — 8 tests
  ```
- Run: `bats tests/unit/`
- All 28 tests passing (2026-06-03)

## Verified Failure Modes (2026-06-03)

| Scenario | Result | Detection |
|---|---|---|
| hostapd with broken config | exit 1, stderr has errors, no SSID | apply_vap.sh captures stderr |
| WPA2 password < 8 chars | exit 1, config validation fails | apply_vap.sh captures stderr |
| Missing bridge in config | exit 0, hostapd AUTO-CREATES the bridge — VAP works but isolated (no eth1.N uplink) | resolve_bridge() warns; not a blocker |
| hostapd binary not found | exit 127, no SSID | process check catches |
| ctrl_interface dir missing | hostapd creates it, works | Not a failure |
| ctrl_interface is a file | exit 1, fails | Not expected in practice |
| Duplicate interface creation | `Invalid argument (-22)` | Collision check catches |
| No hostapd after interface creation | VAP exists, NO SSID (invisible) | Retry + hostapd_alive() check |
| Stale PID file | hostapd overwrites it | Not a failure |
| Interface delete while hostapd running | iw dev del succeeds | Safe cleanup path |
| `type ap` (single underscore) | FAILS — requires management daemon | `type __ap` required |
