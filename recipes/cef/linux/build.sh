#!/usr/bin/env bash
# CEF 8078 (Chromium 156) for os=linux, arch=x86_64 or arm64, with proprietary
# codecs (H.264/AAC in pages, like upstream OBS's CEF),
# obs-rust/obs-studio#1864 and #3062.
#   recipes/cef/linux/build.sh sync|build|pack [x86_64|arm64]
# Steps, so each fits bosn's 4 h run cap and resumes: sync checks out
# depot_tools, Chromium and CEF (hours, once); build runs ninja (re-run until
# it finishes; ninja resumes); pack makes
# cef_binary_8078_linux_<x86_64|aarch64>.tar.xz in the layout obs-studio's
# FindCEF expects (upstream OBS's archive layout: the minimal distribution plus
# build/libcef_dll_wrapper/libcef_dll_wrapper.a).
# The architecture defaults to x86_64, so existing invocations are unchanged.
# arm64 is a cross build from this x86_64 host: automate gets --arm64-build,
# GN gets target_cpu=arm64 with Chromium's own arm64 sysroot, the out directory
# is Release_GN_arm64 and the minimal distribution is `linuxarm64`.
# Everything lives under /cef (bosn.toml mounts the host's out/cef there).
set -euo pipefail

BRANCH=8078
VERSION=8078
WORK=/cef/work
OUT=/cef/dist
# The automate script of exactly this branch.
AUTOMATE_URL="https://raw.githubusercontent.com/chromiumembedded/cef/${BRANCH}/tools/automate/automate-git.py"

# The GN args both architectures share. target_cpu is appended per
# architecture: this host is x86_64, so an arm64 run that leaves it out builds
# x86_64 without saying so. use_sysroot=true selects Chromium's own sysroot for
# the target, which is the arm64 sysroot when target_cpu is arm64.
export GN_DEFINES="is_official_build=true proprietary_codecs=true ffmpeg_branding=Chrome use_sysroot=true symbol_level=1 chrome_pgo_phase=0"
export CEF_ARCHIVE_FORMAT=tar.bz2
export DEPOT_TOOLS_UPDATE=0

usage() {
    echo "usage: $0 sync|build|pack [x86_64|arm64]" >&2
    exit 2
}

# x86_64 -> --x64-build, Release_GN_x64, linux64, archive _linux_x86_64
# arm64  -> --arm64-build, Release_GN_arm64, linuxarm64, archive _linux_aarch64
# The archive names match the obs-studio pin (ci/test_cef_pin.py).
arch_of() {
    arch="${1:-x86_64}"
    case "$arch" in
    x86_64)
        automate_arch=--x64-build
        gn_dir=Release_GN_x64
        distrib_arch=linux64
        asset_arch=x86_64
        target_cpu=x86_64
        ;;
    arm64)
        automate_arch=--arm64-build
        gn_dir=Release_GN_arm64
        distrib_arch=linuxarm64
        asset_arch=aarch64
        target_cpu=arm64
        ;;
    *)
        usage
        ;;
    esac
    export automate_arch
    GN_DEFINES="$GN_DEFINES target_cpu=$target_cpu"
    export GN_DEFINES
    NAME="cef_binary_${VERSION}_linux_${asset_arch}"
}

automate() {
    mkdir -p "$WORK"
    curl -fsSLo "$WORK/automate-git.py" "$AUTOMATE_URL"
    python3 "$WORK/automate-git.py" --download-dir="$WORK" --branch="$BRANCH" \
        "$automate_arch" --no-debug-build --no-chromium-history "$@"
}

build_deps() {
    # DEPOT_TOOLS_UPDATE=0 skips the bootstrap gn and gclient need, so run it here.
    "$WORK/depot_tools/ensure_bootstrap"
    # Chromium's own list of build dependencies, for the checked-out version.
    # --no-arm is the 32-bit ARM host set, not arm64: the arm64 sysroot comes
    # from the depot_tools sysroot hook, for the target_cpu in args.gn.
    "$WORK/chromium/src/build/install-build-deps.sh" --no-prompt --no-chromeos-fonts \
        --no-arm --no-nacl --no-backwards-compatible >/dev/null
    # The gclient hook installs only the sysroot of the architecture it synced,
    # so an arm64 build from this x86_64 host has no arm64 sysroot and
    # cef/tools/gn_args.py silently skips the arm64 configuration ("Not
    # generating arm64 configuration due to missing sysroot directory");
    # automate then fails reading out/Release_GN_arm64/args.gn.
    if [ "$arch" = arm64 ]; then
        python3 "$WORK/chromium/src/build/linux/sysroot_scripts/install-sysroot.py" --arch=arm64
    fi
}

case "${1:-}" in
sync)
    arch_of "${2:-}"
    automate --no-build --no-distrib
    build_deps
    ;;
build)
    arch_of "${2:-}"
    build_deps
    automate --no-update --force-build --minimal-distrib --minimal-distrib-only --no-distrib-archive \
        --build-target=cefsimple
    ;;
pack)
    arch_of "${2:-}"
    distrib="$(ls -d "$WORK"/chromium/src/cef/binary_distrib/cef_binary_*_"${distrib_arch}"_minimal 2>/dev/null | tail -1 || true)"
    if [ -z "$distrib" ] || [ ! -d "$distrib" ]; then
        echo "no ${distrib_arch} minimal distribution under $WORK/chromium/src/cef/binary_distrib" >&2
        exit 1
    fi
    rm -rf "${OUT:?}/$NAME" && mkdir -p "$OUT"
    cp -a "$distrib" "$OUT/$NAME"
    if [ "$arch" = arm64 ]; then
        # The distribution's cmake build compiles the wrapper for this host
        # (x86_64), which would put the wrong object code in an arm64 archive.
        # Take the arm64 wrapper the CEF build already made instead.
        wrapper_src="$WORK/chromium/src/out/$gn_dir/libcef_dll_wrapper/libcef_dll_wrapper.a"
        if [ ! -f "$wrapper_src" ]; then
            echo "no arm64 wrapper at $wrapper_src; run build first" >&2
            exit 1
        fi
        mkdir -p "$OUT/$NAME/build/libcef_dll_wrapper"
        cp "$wrapper_src" "$OUT/$NAME/build/libcef_dll_wrapper/libcef_dll_wrapper.a"
    else
        cmake -S "$OUT/$NAME" -B "$OUT/$NAME/build" -G Ninja -DCMAKE_BUILD_TYPE=Release
        ninja -C "$OUT/$NAME/build" libcef_dll_wrapper
    fi
    # Guard: proprietary codecs are in, the build is the architecture asked for,
    # and the glibc floor stays at or below the AppImage's 2.28 (upstream's 7871
    # needs 2.25).
    args="$WORK/chromium/src/out/$gn_dir/args.gn"
    grep -q 'proprietary_codecs *= *true' "$args" && grep -q 'ffmpeg_branding *= *"Chrome"' "$args" ||
        { echo "$args was not built with proprietary codecs" >&2; exit 1; }
    grep -q "target_cpu *= *\"$target_cpu\"" "$args" ||
        { echo "$args was not built for $target_cpu" >&2; exit 1; }
    floor="$(objdump -T "$OUT/$NAME/Release/libcef.so" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
    echo "libcef.so glibc floor: $floor"
    [ "$(printf '%s\nGLIBC_2.28\n' "$floor" | sort -V | tail -1)" = "GLIBC_2.28" ] ||
        { echo "glibc floor $floor is above 2.28" >&2; exit 1; }
    grep -m1 'define CEF_VERSION ' "$OUT/$NAME/include/cef_version.h"
    tar -C "$OUT" -cJf "$OUT/$NAME.tar.xz" "$NAME"
    sha256sum "$OUT/$NAME.tar.xz"
    chown -R "$(stat -c %u:%g /cef)" "$OUT"
    ;;
*)
    usage
    ;;
esac
