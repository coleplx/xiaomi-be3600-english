# helpers.bash - Shared test utilities for router shell scripts
# Source with: load helpers
# Use: common_setup / common_teardown in your setup()/teardown()

common_setup() {
    TEST_TMPDIR="$(mktemp -d)"
    mkdir -p "$TEST_TMPDIR/bin"
    # Ensure stubs take priority but real commands are still reachable
    PATH="$TEST_TMPDIR/bin:$PATH"
}

common_teardown() {
    rm -rf "$TEST_TMPDIR"
}
