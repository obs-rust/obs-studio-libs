#!/usr/bin/env bash
# libvpl 2.17.0 for os=linux,arch=x86_64,libc=glibc,os_version=2.28 (obs-studio-libs).
# The Intel VPL dispatcher obs-qsv11 builds and links against (AlmaLinux 8 has
# no oneVPL package). Only the dispatcher: the GPU runtime (libmfx-gen,
# libmfxhw64) comes from the host at run time (obs-rust/obs-studio#1863).
PREFIX=/opt/obs-deps/libvpl
VERSION=2.17.0
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

libvpl() {
    # v2.17.0
    git_src libvpl https://github.com/intel/libvpl.git d77f9195cf495b937631607333288fd917ae8939
    cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_SHARED_LIBS=ON -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF \
        -DINSTALL_EXAMPLES=OFF -DBUILD_EXPERIMENTAL=OFF
    cmake --build build -j "$JOBS" && cmake --install build
}

run_steps libvpl
