#!/usr/bin/env bash
# Qt 6 for the glibc 2.28 AppImage base (obs-rust/obs-studio#926): qtbase
# (Core, Gui, Widgets, Network, OpenGL, DBus, Xml, the xcb QPA plugin), qtsvg
# and qtwayland (WaylandClient, wl-shell integration), installed into /opt/obs-deps/qt6.
# These are the Qt libraries the Ubuntu 26.04 AppImage bundled, at the version
# obs-deps (deps.qt/qt6.zsh) ships for Windows and macOS.
set -euo pipefail
[ "$(getconf GNU_LIBC_VERSION)" = "glibc 2.28" ] ||
    { echo "error: $(getconf GNU_LIBC_VERSION), expected exactly glibc 2.28 (recipes/linux/Dockerfile)" >&2; exit 1; }

# Its own prefix: Qt is published on its own (obs-rust/obs-studio-libs, tool
# "qt6"), so the tarball is exactly this directory.
PREFIX="${QT_PREFIX:-/opt/obs-deps/qt6}"
QT_VERSION=6.11.1
VERSION=$QT_VERSION # for the pack task
declare -A SHA256=(
    [qtbase]=d9594a31228aa23ad6b531719a29b45f0f3989fe6c136d45767ea179f233c1ac
    [qtsvg]=7f3cf02f4824bf03c2c5859ea6db173bf1482a1daf24e6cdf7bc78cfa26a8a94
    [qtwayland]=95788aa502f75441d4edf65932b235f76523084e13dbbb7b9ee2d207b32bd9b3
)

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
fetch() {
    local m="$1" f="$1-everywhere-src-$QT_VERSION.tar.xz"
    curl -fsSLo "$f" "https://download.qt.io/official_releases/qt/${QT_VERSION%.*}/$QT_VERSION/submodules/$f"
    echo "${SHA256[$m]}  $f" | sha256sum -c -
    tar -xf "$f"
}

fetch qtbase
# GSSAPI/SPNEGO is unused by OBS (it makes no Negotiate/SPNEGO request), and the
# base's krb5 libraries it pulls in NEED libcrypto.so.1.1, which re-introduced
# EOL OpenSSL 1.1.1k into the AppImage (obs-rust/obs-studio#2815).
cmake -S "qtbase-everywhere-src-$QT_VERSION" -B build-qtbase -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DBUILD_SHARED_LIBS=ON -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF \
    -DFEATURE_xcb=ON -DFEATURE_xcb_xlib=ON -DFEATURE_xkbcommon=ON \
    -DFEATURE_opengl=ON -DFEATURE_opengl_desktop=ON -DFEATURE_egl=ON \
    -DFEATURE_dbus=ON -DFEATURE_dbus_linked=ON -DFEATURE_glib=ON \
    -DFEATURE_fontconfig=ON -DFEATURE_system_freetype=ON \
    -DFEATURE_harfbuzz=ON -DFEATURE_system_harfbuzz=OFF \
    -DFEATURE_system_zlib=ON -DFEATURE_system_png=OFF -DFEATURE_system_jpeg=OFF \
    -DFEATURE_system_pcre2=OFF -DFEATURE_icu=OFF \
    -DFEATURE_openssl=ON -DFEATURE_openssl_linked=OFF -DFEATURE_gssapi=OFF \
    -DFEATURE_sql=OFF -DFEATURE_testlib=OFF -DFEATURE_printsupport=OFF \
    -DFEATURE_concurrent=OFF -DFEATURE_vulkan=OFF \
    -DFEATURE_eglfs=OFF -DFEATURE_linuxfb=OFF -DFEATURE_vnc=OFF -DFEATURE_gtk3=OFF
cmake --build build-qtbase
cmake --install build-qtbase

for m in qtsvg qtwayland; do
    fetch "$m"
    cmake -S "$m-everywhere-src-$QT_VERSION" -B "build-$m" -G Ninja \
        -DCMAKE_PREFIX_PATH="$PREFIX" -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_BUILD_TYPE=Release -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF
    cmake --build "build-$m"
    cmake --install "build-$m"
done
