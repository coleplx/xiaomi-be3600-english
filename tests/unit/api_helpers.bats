#!/usr/bin/env bats

load ../helpers

setup() {
    common_setup
    source "$BATS_TEST_DIRNAME/../fixtures/api_helpers.sh"
}

teardown() {
    common_teardown
}

# ── get_param ──

@test "get_param: extracts key from query string" {
    QS="action=overview&lines=50"
    [ "$(get_param lines)" = "50" ]
}

@test "get_param: returns empty for missing key" {
    QS="a=1&b=2"
    [ -z "$(get_param c)" ]
}

@test "get_param: decodes plus to space" {
    QS="ssid=My+WiFi"
    [ "$(get_param ssid)" = "My WiFi" ]
}

@test "get_param: decodes percent-encoded hex" {
    QS="key=hello%21world"
    [ "$(get_param key)" = "hello!world" ]
}

@test "get_param: handles single param (no leading question mark)" {
    QS="action=overview"
    [ "$(get_param action)" = "overview" ]
}

# ── json_esc ──

@test "json_esc: escapes double quotes" {
    [ "$(json_esc 'say "hi"')" = 'say \"hi\"' ]
}

@test "json_esc: escapes backslashes" {
    [ "$(json_esc 'a\b')" = 'a\\b' ]
}

@test "json_esc: passes plain text" {
    [ "$(json_esc 'hello')" = 'hello' ]
}

@test "json_esc: handles empty string" {
    [ "$(json_esc '')" = '' ]
}

# ── fmt_uptime ──

@test "fmt_uptime: 0s → 0m" {
    [ "$(fmt_uptime 0)" = "0m" ]
}

@test "fmt_uptime: 61s → 1m" {
    [ "$(fmt_uptime 61)" = "1m" ]
}

@test "fmt_uptime: 3599s → 59m" {
    [ "$(fmt_uptime 3599)" = "59m" ]
}

@test "fmt_uptime: 3600s → 1h 0m" {
    [ "$(fmt_uptime 3600)" = "1h 0m" ]
}

@test "fmt_uptime: 3661s → 1h 1m" {
    [ "$(fmt_uptime 3661)" = "1h 1m" ]
}

@test "fmt_uptime: 86400s → 1d 0h 0m" {
    [ "$(fmt_uptime 86400)" = "1d 0h 0m" ]
}

@test "fmt_uptime: 90061s → 1d 1h 1m" {
    [ "$(fmt_uptime 90061)" = "1d 1h 1m" ]
}

# ── fmt_size (bc is missing on router) ──

@test "fmt_size: sub-1024 KB returns direct value" {
    [ "$(fmt_size 500)" = "500 KB" ]
}

@test "fmt_size: MB range falls back to ? MB when bc missing" {
    result=$(fmt_size 2048)
    [ "$result" = "? MB" ]
}

@test "fmt_size: boundary at 1024 stays in KB range" {
    result=$(fmt_size 1024)
    [ "$result" = "1024 KB" ]
}

@test "fmt_size: GB range falls back to ? GB when bc missing" {
    result=$(fmt_size 2097152)
    [ "$result" = "? GB" ]
}
