#!/usr/bin/env bash
# OpenSSL 3.5.9 (LTS) for os=linux,arch=x86_64,libc=glibc,os_version=2.28.
# The AppImage's libcurl is pinned (recipes/linux/curl.sh), and curl 8.18+
# refuses OpenSSL older than 3.0: the AlmaLinux 8 base's 1.1.1k (EOL) cannot be
# linked. This prefix is that TLS runtime, so 3.5 (an LTS line, supported past
# 2030) replaces 1.1.1k for the pinned curl. It is deliberately *not* added to
# the image's CMake/pkg-config path: the rest of the tree still consumes the
# base's 1.1.1k, and re-pointing all of it is its own unit. OpenSSL symbols are
# versioned (`OPENSSL_3.0.0` / `OPENSSL_1_1_0`), so both libraries can be
# loaded in one process. See obs-rust/obs-studio#2774.
PREFIX=/opt/obs-deps/openssl
VERSION=3.5.9
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

openssl_build() {
    tar_src openssl https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz \
        603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a
    # no-tests/no-docs: a dependency prefix, not a distribution. --libdir=lib
    # keeps the layout of every other tool here.
    ./Configure --prefix="$PREFIX" --libdir=lib --openssldir="$PREFIX/ssl" \
        shared no-tests no-docs linux-x86_64
    make -j"$JOBS"
    make install_sw install_ssldirs
    # The runtime libcurl opens with: prove the prefix really is 3.5.9 and that
    # it resolved this build, not the base's 1.1.1k.
    LD_LIBRARY_PATH="$PREFIX/lib" "$PREFIX/bin/openssl" version |
        grep -q "Library: OpenSSL $VERSION " ||
        { echo "error: $PREFIX/bin/openssl does not load OpenSSL $VERSION" >&2; exit 1; }
    LD_LIBRARY_PATH="$PREFIX/lib" "$PREFIX/bin/openssl" version
}

run_steps openssl_build
