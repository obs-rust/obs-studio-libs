#!/usr/bin/env bash
# libdatachannel 0.24.6 for os=linux,arch=x86_64,libc=glibc,os_version=2.28 (obs-studio-libs).
# obs-webrtc's WebRTC transport (WHIP output), obs-rust/obs-studio#1744. Built
# against the image's OpenSSL, which the AppImage already bundles for libcurl,
# with its submodules (libjuice, usrsctp, libsrtp, plog) linked in statically.
PREFIX=/opt/obs-deps/libdatachannel
VERSION=0.24.6
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

libdatachannel() {
    git_src libdatachannel https://github.com/paullouisageneau/libdatachannel.git 6b1e2e620f1e37f0eafeee702eaea0043cb305fd
    cmake_build -DUSE_GNUTLS=OFF -DUSE_MBEDTLS=OFF -DUSE_NICE=OFF -DNO_MEDIA=OFF -DNO_WEBSOCKET=ON \
        -DNO_EXAMPLES=ON -DNO_TESTS=ON -DPREFER_SYSTEM_LIB=OFF
    [ -f "$PREFIX/lib/libdatachannel.so.$VERSION" ] ||
        { echo "error: libdatachannel.so.$VERSION was not installed" >&2; exit 1; }
}

run_steps libdatachannel
