#!/usr/bin/env bash
# CEF 8078 (Chromium 156) for os=windows, arch=x64 or arm64, cross-built from
# Linux, obs-rust/obs-studio#2417 and #1864.
#   recipes/cef/windows/build.sh sync|toolchain|build|pack [x64|arm64]
# Steps, so each fits bosn's 4 h run cap and resumes: sync checks out
# depot_tools, Chromium and CEF (hours, once); toolchain turns soldr's xwin
# payload into the depot_tools win_toolchain zip (minutes); build runs gn gen
# with target_os="win" plus ninja (re-run until it finishes; ninja resumes);
# pack makes cef_binary_8078_windows_<x64|arm64>.zip in the layout obs-studio's
# FindCEF expects (the minimal distribution plus the built
# libcef_dll_wrapper.lib). The architecture defaults to x64.
#
# Why this is not the Linux recipe with another flag: CEF's automate-git.py on
# branch 8078 has no target-OS switch — its only arch flags are --x64-build and
# --arm64-build and it derives the host OS — so automate can sync but cannot
# build for Windows. The build step therefore calls GN directly, with
# target_os="win" and the packaged toolchain. Nothing here has been proven to
# produce a working Windows archive yet: the GN configure against the packaged
# toolchain is the fork in the road (#2417).
# Everything lives under /cef (bosn.toml mounts the host's out/cef there).
set -euo pipefail

BRANCH=8078
VERSION=8078
WORK=/cef/work
OUT=/cef/dist
TOOLCHAIN_OUT=/cef/win-toolchain
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The automate script of exactly this branch.
AUTOMATE_URL="https://raw.githubusercontent.com/chromiumembedded/cef/${BRANCH}/tools/automate/automate-git.py"
# build/vs_toolchain.py's TOOLCHAIN_HASH; the override variable is
# GYP_MSVS_HASH_<hash>, and it is what makes depot_tools fetch our zip instead
# of Google's internal package.
TOOLCHAIN_HASH=3bfcb536c8
# The xwin payload soldr resolves for this target carries both arches.
TOOLCHAIN_TARGET=x86_64-pc-windows-msvc

# The GN args both architectures share. target_cpu and target_os are appended
# per architecture: this host is Linux, so leaving target_os out builds a Linux
# tree that happens to live under a Windows out directory. No use_sysroot: the
# Chromium sysroot is for Linux targets, and a Windows build takes its headers
# and libs from the packaged toolchain.
export GN_DEFINES="is_official_build=true proprietary_codecs=true ffmpeg_branding=Chrome symbol_level=1 chrome_pgo_phase=0"
export DEPOT_TOOLS_UPDATE=0
# The CEF distribution is zipped, not tarred, on Windows.
export CEF_ARCHIVE_FORMAT=zip

usage() {
    echo "usage: $0 sync|toolchain|build|pack [x64|arm64]" >&2
    exit 2
}

# x64   -> --x64-build, Release_GN_x64, windows64, archive _windows_x64
# arm64 -> --arm64-build, Release_GN_arm64, windowsarm64, archive _windows_arm64
# The archive names match obs-studio's pin (ci/test_cef_pin.py).
arch_of() {
    arch="${1:-x64}"
    case "$arch" in
    x64)
        automate_arch=--x64-build
        gn_dir=Release_GN_x64
        distrib_arch=windows64
        target_cpu=x64
        ;;
    arm64)
        automate_arch=--arm64-build
        gn_dir=Release_GN_arm64
        distrib_arch=windowsarm64
        target_cpu=arm64
        ;;
    *)
        usage
        ;;
    esac
    export automate_arch
    GN_DEFINES="$GN_DEFINES target_os=\"win\" target_cpu=\"$target_cpu\""
    export GN_DEFINES
    NAME="cef_binary_${VERSION}_windows_${arch}"
    export NAME
}

automate() {
    mkdir -p "$WORK"
    curl -fsSLo "$WORK/automate-git.py" "$AUTOMATE_URL"
    python3 "$WORK/automate-git.py" --download-dir="$WORK" --branch="$BRANCH" \
        "$automate_arch" --no-debug-build --no-chromium-history "$@"
}

# gn and ninja live in the synced tree; depot_tools' wrappers want a git
# checkout they can bootstrap from, so prefer the pinned binaries.
gn_bin() {
    if [ -x "$WORK/chromium/src/buildtools/linux64/gn" ]; then
        echo "$WORK/chromium/src/buildtools/linux64/gn"
    else
        echo "$WORK/depot_tools/gn"
    fi
}

ninja_bin() {
    if [ -x "$WORK/chromium/src/third_party/ninja/ninja" ]; then
        echo "$WORK/chromium/src/third_party/ninja/ninja"
    else
        echo "$WORK/depot_tools/ninja"
    fi
}

toolchain() {
    # depot_tools hashes the toolchain with os.walk, which does not follow
    # symlinked directories, and Chromium's build on Linux needs the SDK on a
    # case-insensitive filesystem (#pragma once and
    # -Wnonportable-include-path otherwise break), so the extracted tree is
    # real files under a ciopfs mount (build/vs_toolchain.py makes that mount
    # itself; this only checks the tool is there).
    if ! command -v ciopfs >/dev/null 2>&1; then
        echo "ciopfs is not installed; build/vs_toolchain.py needs it on Linux" >&2
        exit 1
    fi
    xwin="$(soldr cc --target "$TOOLCHAIN_TARGET" --print-sysroot)"
    python3 "$HERE/package_win_toolchain.py" package --xwin "$xwin" --out "$TOOLCHAIN_OUT"
    digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha1"])' \
        "$TOOLCHAIN_OUT/toolchain.json")"
    export DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL="file://$TOOLCHAIN_OUT"
    export DEPOT_TOOLS_WIN_TOOLCHAIN=1
    export "GYP_MSVS_HASH_${TOOLCHAIN_HASH}=${digest}"
    echo "toolchain $digest served from $TOOLCHAIN_OUT"
}

build() {
    toolchain
    src="$WORK/chromium/src"
    # gclient's hook materializes the toolchain under depot_tools/win_toolchain
    # from DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL; it is what writes
    # build/win_toolchain.json, which GN reads for VC and the SDK.
    (cd "$src" && python3 build/vs_toolchain.py update)
    "$(gn_bin)" gen "$src/out/$gn_dir" --args="$GN_DEFINES" --root="$src"
    "$(ninja_bin)" -C "$src/out/$gn_dir" cefclient
}

casesync() {
    # Anything after the architecture goes to automate-git.py, so a CEF branch
    # that moved its Chromium tag can be re-synced with --force-update.
    extra=()
    if [ "$#" -gt 2 ]; then extra=("${@:3}"); fi
    if [ -d "$WORK/chromium/src" ] && [ ! -f "$WORK/chromium/src/chrome/VERSION" ] &&
        [[ " ${extra[*]-} " == *" --force-update "* ]]; then
        echo "removing incomplete Chromium checkout under $WORK/chromium" >&2
        rm -rf "${WORK:?}/chromium"
    fi
    automate --no-build --no-distrib "${extra[@]}"
    # The Linux host build dependencies (fonts, X, pkgconfig) are still what
    # the GN toolchain and CEF's own generators run on.
    "$WORK/depot_tools/ensure_bootstrap"
    "$WORK/chromium/src/build/install-build-deps.sh" --no-prompt --no-chromeos-fonts \
        --no-arm --no-nacl --no-backwards-compatible >/dev/null
}

case "${1:-}" in
sync)
    arch_of "${2:-}"
    casesync "$@"
    ;;
toolchain)
    arch_of "${2:-}"
    toolchain
    ;;
build)
    arch_of "${2:-}"
    build
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
    # The distribution's CMake build would compile the wrapper with this host's
    # compiler (and no MSVC), which would put Linux objects in a Windows
    # archive; take the wrapper the CEF build made for the target instead.
    wrapper="$WORK/chromium/src/out/$gn_dir/libcef_dll_wrapper/libcef_dll_wrapper.lib"
    if [ ! -f "$wrapper" ]; then
        echo "no Windows wrapper at $wrapper; run build first" >&2
        exit 1
    fi
    mkdir -p "$OUT/$NAME/libcef_dll_wrapper"
    cp "$wrapper" "$OUT/$NAME/libcef_dll_wrapper/libcef_dll_wrapper.lib"
    args="$WORK/chromium/src/out/$gn_dir/args.gn"
    # Guard: proprietary codecs are in, and the build is the OS and
    # architecture asked for rather than the host's.
    grep -q 'proprietary_codecs *= *true' "$args" && grep -q 'ffmpeg_branding *= *"Chrome"' "$args" ||
        { echo "$args was not built with proprietary codecs" >&2; exit 1; }
    grep -q 'target_os *= *"win"' "$args" || { echo "$args was not built for Windows" >&2; exit 1; }
    grep -q "target_cpu *= *\"$target_cpu\"" "$args" ||
        { echo "$args was not built for $target_cpu" >&2; exit 1; }
    grep -m1 'define CEF_VERSION ' "$OUT/$NAME/include/cef_version.h"
    (cd "$OUT" && zip -qr "$NAME.zip" "$NAME")
    sha256sum "$OUT/$NAME.zip"
    chown -R "$(stat -c %u:%g /cef)" "$OUT"
    ;;
*)
    usage
    ;;
esac
