#!/usr/bin/env bash
# libdatachannel 0.24.6 for os=linux,arch=x86_64,libc=glibc,os_version=2.28 (obs-studio-libs).
# obs-webrtc's WebRTC transport (WHIP output), obs-rust/obs-studio#1744. Built
# against the pinned OpenSSL 3.5.9 prefix (recipes/linux/openssl.sh), with its
# submodules (libjuice, usrsctp, libsrtp, plog) linked in statically.
#
# Not the base image's OpenSSL 1.1.1k (EOL): libdatachannel used to be the one
# appended object in the AppImage with `NEEDED libssl.so.1.1` /
# `libcrypto.so.1.1`, which kept 1.1.1 in the bundle next to the pinned 3.5.9
# and left Qt Network - it `dlopen`s OpenSSL and takes the first versioned
# soname it finds - speaking 1.1.1 (obs-rust/obs-studio#2774).
PREFIX=/opt/obs-deps/libdatachannel
VERSION=0.24.6
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

# common.sh points pkg-config and CMake at $PREFIX only; add the pinned
# OpenSSL so both resolve it instead of the image's /usr/lib64 1.1.1k.
export PKG_CONFIG_PATH="/opt/obs-deps/openssl/lib/pkgconfig:$PKG_CONFIG_PATH"
export CMAKE_PREFIX_PATH="/opt/obs-deps/openssl:$CMAKE_PREFIX_PATH"

libdatachannel() {
    git_src libdatachannel https://github.com/paullouisageneau/libdatachannel.git 6b1e2e620f1e37f0eafeee702eaea0043cb305fd
    cmake_build -DUSE_GNUTLS=OFF -DUSE_MBEDTLS=OFF -DUSE_NICE=OFF -DNO_MEDIA=OFF -DNO_WEBSOCKET=ON \
        -DNO_EXAMPLES=ON -DNO_TESTS=ON -DPREFER_SYSTEM_LIB=OFF \
        -DOPENSSL_ROOT_DIR=/opt/obs-deps/openssl
    [ -f "$PREFIX/lib/libdatachannel.so.$VERSION" ] ||
        { echo "error: libdatachannel.so.$VERSION was not installed" >&2; exit 1; }
    # Asserted at build time: TLS must be the pinned OpenSSL 3, never 1.1.1.
    LD_LIBRARY_PATH="/opt/obs-deps/openssl/lib:$PREFIX/lib" \
        ldd "$PREFIX/lib/libdatachannel.so.$VERSION" >"$work/ldd.txt"
    grep -q '/opt/obs-deps/openssl/lib/libssl\.so\.3' "$work/ldd.txt" ||
        { echo "error: libdatachannel does not link the pinned OpenSSL 3 prefix" >&2; exit 1; }
    ! grep -q '/libssl\.so\.1' "$work/ldd.txt" ||
        { echo "error: libdatachannel still links OpenSSL 1.1 (EOL)" >&2; exit 1; }
    cat "$work/ldd.txt"
}

run_steps libdatachannel
