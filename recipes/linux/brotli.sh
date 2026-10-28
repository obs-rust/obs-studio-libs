#!/usr/bin/env bash
# brotli 1.2.1 for os=linux,arch=x86_64,libc=glibc,os_version=2.28 (obs-studio-libs).
# The Brotli codec the AppImage's libcurl decodes with. The AlmaLinux 8 base
# supplies 1.0.6, which is inside CVE-2026-111497's range (1.0.3-1.2.0), so the
# outgoing-HTTP stop-gap in obs-rust/obs-studio#2211 cannot be reverted until a
# fixed brotli ships in the AppImage (obs-rust/obs-studio#2774). 1.2.1 is the
# first release past the vulnerable range.
PREFIX=/opt/obs-deps/brotli
VERSION=1.2.1
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

brotli() {
    # v1.2.1
    git_src brotli https://github.com/google/brotli.git db24a98aed38a16de78cc05ca15cdd8dc2a0d92d
    cmake_build -DBROTLI_DISABLE_TESTS=ON
}

run_steps brotli
