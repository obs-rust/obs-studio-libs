#!/usr/bin/env bash
# CEF 8078 (Chromium 156) for os=linux,arch=x86_64 with proprietary codecs
# (H.264/AAC in pages, like upstream OBS's CEF), obs-rust/obs-studio#1864.
#   recipes/cef/linux/build.sh sync|build|pack
# Steps, so each fits bosn's 4 h run cap and resumes: sync checks out
# depot_tools, Chromium and CEF (hours, once); build runs ninja (re-run until
# it finishes; ninja resumes); pack makes cef_binary_8078_linux_x86_64.tar.xz in
# the layout obs-studio's FindCEF expects (upstream OBS's archive layout: the
# minimal distribution plus build/libcef_dll_wrapper/libcef_dll_wrapper.a).
# Everything lives under /cef (bosn.toml mounts the host's out/cef there).
set -euo pipefail

BRANCH=8078
VERSION=8078
WORK=/cef/work
OUT=/cef/dist
NAME="cef_binary_${VERSION}_linux_x86_64"
# The automate script of exactly this branch.
AUTOMATE_URL="https://raw.githubusercontent.com/chromiumembedded/cef/${BRANCH}/tools/automate/automate-git.py"

export GN_DEFINES="is_official_build=true proprietary_codecs=true ffmpeg_branding=Chrome use_sysroot=true symbol_level=0 chrome_pgo_phase=0"
export CEF_ARCHIVE_FORMAT=tar.bz2
export DEPOT_TOOLS_UPDATE=0

automate() {
    mkdir -p "$WORK"
    curl -fsSLo "$WORK/automate-git.py" "$AUTOMATE_URL"
    python3 "$WORK/automate-git.py" --download-dir="$WORK" --branch="$BRANCH" \
        --x64-build --no-debug-build --no-chromium-history "$@"
}

build_deps() {
    # DEPOT_TOOLS_UPDATE=0 skips the bootstrap gn and gclient need, so run it here.
    "$WORK/depot_tools/ensure_bootstrap"
    # Chromium's own list of build dependencies, for the checked-out version.
    "$WORK/chromium/src/build/install-build-deps.sh" --no-prompt --no-chromeos-fonts \
        --no-arm --no-nacl --no-backwards-compatible >/dev/null
}

case "${1:-}" in
sync)
    automate --no-build --no-distrib
    build_deps
    ;;
build)
    build_deps
    automate --no-update --force-build --minimal-distrib --minimal-distrib-only --no-distrib-archive \
        --build-target=cefsimple
    ;;
pack)
    distrib="$(ls -d "$WORK"/chromium/src/cef/binary_distrib/cef_binary_*_linux64_minimal | tail -1)"
    rm -rf "${OUT:?}/$NAME" && mkdir -p "$OUT"
    cp -a "$distrib" "$OUT/$NAME"
    cmake -S "$OUT/$NAME" -B "$OUT/$NAME/build" -G Ninja -DCMAKE_BUILD_TYPE=Release
    ninja -C "$OUT/$NAME/build" libcef_dll_wrapper
    # Guard: proprietary codecs are in, and the glibc floor stays at or below
    # the AppImage's 2.28 (upstream's 7871 needs 2.25).
    args="$WORK/chromium/src/out/Release_GN_x64/args.gn"
    grep -q 'proprietary_codecs *= *true' "$args" && grep -q 'ffmpeg_branding *= *"Chrome"' "$args" ||
        { echo "$args was not built with proprietary codecs" >&2; exit 1; }
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
    echo "usage: $0 sync|build|pack" >&2
    exit 2
    ;;
esac
