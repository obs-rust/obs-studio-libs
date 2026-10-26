#!/usr/bin/env bash
# CEF 8078 (Chromium 156) for macOS arm64 and x86_64 with proprietary codecs
# (H.264/AAC in pages, like upstream OBS's CEF), obs-rust/obs-studio#2418.
#   recipes/cef/macos/build.sh sync|build|pack arm64|x86_64
# The script runs on the Mac. Chromium's macOS build needs Xcode, and the
# bosn stacks in this repo are Linux containers.
# Checkout is 426920c33ef22551e0b8f48cf343d623ac25642d, the commit the Linux
# 8078 archive was built from. Do not add use_sysroot=true; that flag selects
# Chromium's Linux sysroot.
# sync once (the arch flag only satisfies automate; the checkout is shared).
# build one architecture (re-run until it finishes; ninja resumes while that
# out directory is still there). pack writes
# cef_binary_8078_macos_<arch>.tar.xz in the layout obs-studio's FindCEF
# expects, then deletes that arch's out directory so the other arch fits
# on a disk with about 160 GB free.
set -euo pipefail

BRANCH=8078
VERSION=8078
CHECKOUT=426920c33ef22551e0b8f48cf343d623ac25642d
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
WORK="${CEF_WORK:-$ROOT/out/cef/work}"
OUT="${CEF_OUT:-$ROOT/out/cef/dist}"
# The automate script of exactly this commit, so a later branch tip cannot
# change the flags under us.
AUTOMATE_URL="https://raw.githubusercontent.com/chromiumembedded/cef/${CHECKOUT}/tools/automate/automate-git.py"

export GN_DEFINES="is_official_build=true proprietary_codecs=true ffmpeg_branding=Chrome symbol_level=1 chrome_pgo_phase=0"
export DEPOT_TOOLS_UPDATE=0

usage() {
    echo "usage: $0 sync|build|pack arm64|x86_64" >&2
    exit 2
}

# arm64 -> --arm64-build, Release_GN_arm64, distrib macosarm64
# x86_64 -> --x64-build, Release_GN_x64, distrib macosx64
# Archive names match cmake/macos/buildspec.cmake (empty revision stripped):
# cef_binary_8078_macos_arm64 and cef_binary_8078_macos_x86_64.
arch_of() {
    arch="${1:-}"
    case "$arch" in
    arm64)
        automate_arch=--arm64-build
        gn_dir=Release_GN_arm64
        distrib_arch=macosarm64
        project_arch=arm64
        # The hook on this host would also write Debug_GN_arm64.
        export GN_OUT_CONFIGS=Release_GN_arm64
        ;;
    x86_64)
        automate_arch=--x64-build
        gn_dir=Release_GN_x64
        distrib_arch=macosx64
        project_arch=x86_64
        # An arm64 Mac only writes Release_GN_arm64 unless this is set.
        # GN_OUT_CONFIGS stops the hook from recreating the arm64 out directory.
        export CEF_ENABLE_AMD64=1
        export GN_OUT_CONFIGS=Release_GN_x64
        ;;
    *)
        usage
        ;;
    esac
    NAME="cef_binary_${VERSION}_macos_${arch}"
}

require_host() {
    missing=0
    for cmd in python3 git curl cmake xcodebuild lipo; do
        if ! command -v "$cmd" >/dev/null; then
            echo "missing $cmd" >&2
            missing=1
        fi
    done
    [ "$missing" = 0 ]
    xcodebuild -version
    xcode-select -p
}

free_gib() {
    df -k "$ROOT" | awk 'NR==2 {printf "%.0f\n", $4/1024/1024}'
}

automate() {
    mkdir -p "$WORK"
    curl -fsSLo "$WORK/automate-git.py" "$AUTOMATE_URL"
    python3 "$WORK/automate-git.py" --download-dir="$WORK" --branch="$BRANCH" \
        --checkout="$CHECKOUT" --no-chromium-history --no-debug-build \
        "$automate_arch" "$@"
}

bootstrap() {
    export PATH="$WORK/depot_tools:$PATH"
    # depot_tools/ninja is a wrapper. It finds the real binary only when the
    # current directory is the Chromium tree, so cmake's `ninja --version`
    # probe from the CEF distribution fails. Prefer the Mach-O ninja.
    if [ -x "$WORK/chromium/src/third_party/ninja/ninja" ]; then
        export PATH="$WORK/chromium/src/third_party/ninja:$PATH"
    fi
    "$WORK/depot_tools/ensure_bootstrap"
    ninja_bin="$(command -v ninja)"
    case "$ninja_bin" in
    *.py|*/depot_tools/ninja)
        echo "ninja on PATH is the depot_tools wrapper ($ninja_bin)" >&2
        exit 1
        ;;
    esac
    "$ninja_bin" --version >/dev/null
}

case "${1:-}" in
sync)
    arch_of "${2:-}"
    require_host
    echo "free disk: $(free_gib) GiB"
    echo "sync $arch at $CHECKOUT"
    automate --no-build --no-distrib
    bootstrap
    echo "CEF_MACOS_SYNC_OK $arch"
    ;;
build)
    arch_of "${2:-}"
    require_host
    free="$(free_gib)"
    echo "free disk: ${free} GiB"
    # One Release out directory needs the rest of the disk. Pack removes it.
    if [ "$free" -lt 70 ]; then
        echo "need at least 70 GiB free before ninja (have ${free})" >&2
        exit 1
    fi
    bootstrap
    echo "build $arch ($gn_dir), target cefclient"
    automate --no-update --force-build --minimal-distrib --minimal-distrib-only \
        --no-distrib-archive --build-target=cefclient
    echo "CEF_MACOS_BUILD_OK $arch"
    ;;
pack)
    arch_of "${2:-}"
    require_host
    bootstrap
    distrib="$(ls -d "$WORK"/chromium/src/cef/binary_distrib/cef_binary_*_"${distrib_arch}"_minimal 2>/dev/null | tail -1 || true)"
    if [ -z "$distrib" ] || [ ! -d "$distrib" ]; then
        echo "no ${distrib_arch} minimal distribution under $WORK/chromium/src/cef/binary_distrib" >&2
        exit 1
    fi
    # The symbols sibling is a second copy of the dSYMs. The archive is the
    # minimal directory only, so drop the copy before compressing.
    rm -rf "$WORK"/chromium/src/cef/binary_distrib/cef_binary_*_"${distrib_arch}"_minimal_release_symbols \
        "$WORK"/chromium/src/cef/binary_distrib/cef_binary_*_"${distrib_arch}"_minimal_debug_symbols
    rm -rf "${OUT:?}/$NAME"
    mkdir -p "$OUT"
    cp -a "$distrib" "$OUT/$NAME"
    # PROJECT_ARCH selects the wrapper slice. On an arm64 host the default
    # is arm64, which would put the wrong object code in the x86_64 archive.
    # CEF's cmake pins the deployment target at 13.0, matching obs-studio.
    cmake -S "$OUT/$NAME" -B "$OUT/$NAME/build" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DPROJECT_ARCH="$project_arch"
    ninja -C "$OUT/$NAME/build" libcef_dll_wrapper
    wrapper=""
    for candidate in \
        "$OUT/$NAME/build/libcef_dll_wrapper/libcef_dll_wrapper.a" \
        "$OUT/$NAME/build/libcef_dll_wrapper.a" \
        "$OUT/$NAME/build/libcef_dll/libcef_dll_wrapper.a"
    do
        if [ -f "$candidate" ]; then
            wrapper="$candidate"
            break
        fi
    done
    if [ -z "$wrapper" ]; then
        echo "libcef_dll_wrapper.a was not built" >&2
        exit 1
    fi
    echo "wrapper: $wrapper"
    args="$WORK/chromium/src/out/$gn_dir/args.gn"
    grep -q 'proprietary_codecs *= *true' "$args" && grep -q 'ffmpeg_branding *= *"Chrome"' "$args" ||
        { echo "$args was not built with proprietary codecs" >&2; exit 1; }
    grep -q 'is_official_build *= *true' "$args" ||
        { echo "$args is not an official build" >&2; exit 1; }
    grep -q 'symbol_level *= *1' "$args" ||
        { echo "$args does not keep line tables (symbol_level=1)" >&2; exit 1; }
    if grep -q 'use_sysroot *= *true' "$args"; then
        echo "$args enabled the Linux sysroot" >&2
        exit 1
    fi
    sandbox="$OUT/$NAME/Release/Chromium Embedded Framework.framework/Libraries/libcef_sandbox.dylib"
    if [ ! -f "$sandbox" ]; then
        echo "missing $sandbox" >&2
        exit 1
    fi
    framework="$OUT/$NAME/Release/Chromium Embedded Framework.framework/Chromium Embedded Framework"
    lipo_info="$(lipo -info "$framework")"
    echo "$lipo_info"
    case "$lipo_info" in
    *"$arch"*) ;;
    *)
        echo "framework is not $arch" >&2
        exit 1
        ;;
    esac
    sandbox_info="$(lipo -info "$sandbox")"
    echo "$sandbox_info"
    case "$sandbox_info" in
    *"$arch"*) ;;
    *)
        echo "libcef_sandbox.dylib is not $arch" >&2
        exit 1
        ;;
    esac
    grep -m1 'define CEF_VERSION ' "$OUT/$NAME/include/cef_version.h"
    COPYFILE_DISABLE=1 tar -C "$OUT" -cJf "$OUT/$NAME.tar.xz" "$NAME"
    shasum -a 256 "$OUT/$NAME.tar.xz"
    # Only after the archive exists. A failed pack leaves the out directory.
    rm -rf "$WORK/chromium/src/out/$gn_dir"
    echo "CEF_MACOS_PACK_OK $OUT/$NAME.tar.xz"
    ;;
*)
    usage
    ;;
esac
