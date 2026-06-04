#!/usr/bin/env bats

load ../helpers

setup() {
    common_setup
    source "$BATS_TEST_DIRNAME/../fixtures/apply_vap_helpers.sh"
}

teardown() {
    common_teardown
}

# ── resolve_bridge ──

@test "resolve_bridge: 'lan' returns br-lan" {
    [ "$(resolve_bridge lan)" = "br-lan" ]
}

@test "resolve_bridge: existing bridge returns br-<name>" {
    NET_BASE="$TEST_TMPDIR/sys/class/net"
    mkdir -p "$NET_BASE/br-guest/bridge"
    [ "$(resolve_bridge guest)" = "br-guest" ]
}

@test "resolve_bridge: missing bridge returns empty" {
    [ -z "$(resolve_bridge nonexistent)" ]
}

# ── gen_config_minimal ──

@test "gen_config: open network has no WPA fields" {
    rm -f /tmp/test_hostapd.conf
    gen_config_minimal wl10 wifi1 "OpenNet" "none" "" "lan"
    [ -f /tmp/test_hostapd.conf ]
    grep -q "ssid=OpenNet" /tmp/test_hostapd.conf
    grep -q "bridge=br-lan" /tmp/test_hostapd.conf
    grep -q "driver=nl80211" /tmp/test_hostapd.conf
    grep -q "auth_algs=1" /tmp/test_hostapd.conf
    ! grep -q "wpa=" /tmp/test_hostapd.conf
    rm -f /tmp/test_hostapd.conf
}

@test "gen_config: includes radio-specific fields for wifi1 (5G)" {
    rm -f /tmp/test_hostapd.conf
    gen_config_minimal wl00 wifi1 "Test5G" "none" "" "lan"
    grep -q "hw_mode=a" /tmp/test_hostapd.conf
    grep -q "ieee80211be=1" /tmp/test_hostapd.conf
    grep -q "ignore_broadcast_ssid=0" /tmp/test_hostapd.conf
    rm -f /tmp/test_hostapd.conf
}

@test "gen_config: encrypted network includes WPA2-PSK" {
    rm -f /tmp/test_hostapd.conf
    gen_config_minimal wl10 wifi0 "SecureNet" "psk2" "mypassword" "lan"
    grep -q "wpa=2" /tmp/test_hostapd.conf
    grep -q "wpa_key_mgmt=WPA-PSK" /tmp/test_hostapd.conf
    grep -q "wpa_pairwise=CCMP" /tmp/test_hostapd.conf
    grep -q "wpa_passphrase=mypassword" /tmp/test_hostapd.conf
    grep -q "auth_algs=1" /tmp/test_hostapd.conf
    rm -f /tmp/test_hostapd.conf
}

@test "gen_config: encrypted network without passphrase omits wpa_passphrase" {
    rm -f /tmp/test_hostapd.conf
    gen_config_minimal wl10 wifi0 "NoPass" "psk2" "" "lan"
    grep -q "wpa=2" /tmp/test_hostapd.conf
    ! grep -q "wpa_passphrase" /tmp/test_hostapd.conf
    rm -f /tmp/test_hostapd.conf
}

@test "gen_config: non-lan network uses br-<network> bridge" {
    rm -f /tmp/test_hostapd.conf
    gen_config_minimal wl10 wifi0 "VlanNet" "none" "" "vlan_100"
    grep -q "bridge=br-vlan_100" /tmp/test_hostapd.conf
    rm -f /tmp/test_hostapd.conf
}

@test "gen_config: bridge auto-created by hostapd if not present" {
    rm -f /tmp/test_hostapd.conf
    # Even for a non-existent VLAN bridge, gen_config should succeed
    # because hostapd auto-creates missing bridges
    gen_config_minimal wl10 wifi0 "VlanNet" "none" "" "vlan_999"
    [ -f /tmp/test_hostapd.conf ]
    grep -q "bridge=br-vlan_999" /tmp/test_hostapd.conf
    rm -f /tmp/test_hostapd.conf
}
