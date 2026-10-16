#!/usr/bin/env bash
# ffmpeg 8.1.2 for os=linux,arch=x86_64,libc=glibc,os_version=2.28 (obs-studio-libs).
# FFmpeg and the codecs it links, with obs-deps' pins (deps.ffmpeg/): one artifact, because
# FFmpeg is built against these exact codec builds.
PREFIX=/opt/obs-deps/ffmpeg
VERSION=8.1.2
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

ogg() { git_src ogg https://github.com/xiph/ogg.git fa80aae9d50096160f2b56ada35527d7aee3f746 && cmake_build -DINSTALL_DOCS=OFF; }
vorbis() { git_src vorbis https://gitlab.xiph.org/xiph/vorbis.git 2eac96b03ff67953354cb0a649c08aa3a23267ef && cmake_build; }
opus() {
    git_src opus https://github.com/xiph/opus.git ddbe48383984d56acd9e1ab6a090c54ca6b735a6
    cmake_build -DOPUS_BUILD_PROGRAMS=OFF -DOPUS_BUILD_TESTING=OFF -DOPUS_ENABLE_FLOAT_API=ON
}
vorbis() { git_src vorbis https://gitlab.xiph.org/xiph/vorbis.git 2eac96b03ff67953354cb0a649c08aa3a23267ef && cmake_build; }
opus() {
    git_src opus https://github.com/xiph/opus.git ddbe48383984d56acd9e1ab6a090c54ca6b735a6
    cmake_build -DOPUS_BUILD_PROGRAMS=OFF -DOPUS_BUILD_TESTING=OFF -DOPUS_ENABLE_FLOAT_API=ON
}
opus() {
    git_src opus https://github.com/xiph/opus.git ddbe48383984d56acd9e1ab6a090c54ca6b735a6
    cmake_build -DOPUS_BUILD_PROGRAMS=OFF -DOPUS_BUILD_TESTING=OFF -DOPUS_ENABLE_FLOAT_API=ON
}
vpx() {
    tar_src vpx https://github.com/webmproject/libvpx/archive/v1.14.1.tar.gz \
        901747254d80a7937c933d03bd7c5d41e8e6c883e0665fadcb172542167c7977
    ./configure --prefix="$PREFIX" --enable-shared --disable-static --enable-pic --enable-vp9-highbitdepth \
        --disable-examples --disable-tools --disable-docs --disable-unit-tests
    make -j"$JOBS" && make install
}
svtav1() {
    git_src svtav1 https://gitlab.com/AOMediaCodec/SVT-AV1.git 6e69def4ec283fe0b71195671245c3b768bebdef
    cmake_build -DBUILD_APPS=OFF -DBUILD_DEC=OFF -DBUILD_TESTING=OFF
}
aom() {
    git_src aom https://aomedia.googlesource.com/aom.git d772e334cc724105040382a977ebb10dfd393293
    mkdir -p "$work/aom-build" && cd "$work/aom-build"
    cmake "$work/aom" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
        -DBUILD_SHARED_LIBS=ON -DENABLE_DOCS=OFF -DENABLE_EXAMPLES=OFF -DENABLE_TESTS=OFF -DENABLE_TOOLS=OFF
    cmake --build . && cmake --install .
}
x264() {
    git_src x264 https://github.com/mirror/x264.git eaa68fad9e5d201d42fde51665f2d137ae96baf0
    ./configure --prefix="$PREFIX" --enable-shared --enable-pic --disable-cli --disable-lavf --disable-swscale
    make -j"$JOBS" && make install
}
theora() {
    tar_src theora https://ftp.osuosl.org/pub/xiph/releases/theora/libtheora-1.1.1.tar.xz \
        f36da409947aa2b3dcc6af0a8c2e3144bc19db2ed547d64e9171c59c66561c61
    # 1.1.1's config.guess predates current systems; refresh it from automake.
    cp /usr/share/automake-*/config.guess /usr/share/automake-*/config.sub . 2>/dev/null || true
    autotools --disable-examples --disable-spec --disable-doc --disable-oggtest --disable-vorbistest \
        --with-ogg="$PREFIX" --with-vorbis="$PREFIX"
    # theora 1.1.1 links libtheoraenc without libtheoradec, whose th_comment_*
    # functions it uses: declare the dependency so the library loads on its own.
    patchelf --add-needed libtheoradec.so.1 "$PREFIX/lib/libtheoraenc.so.1"
}
lame() {
    tar_src lame https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz \
        ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e
    # lame 3.100 exports a symbol it no longer defines.
    sed -i '/lame_init_old/d' include/libmp3lame.sym
    autotools --disable-frontend --disable-decoder --disable-gtktest
}
mbedtls() {
    git_src mbedtls https://github.com/Mbed-TLS/mbedtls.git c765c831e5c2a0971410692f92f7a81d6ec65ec2
    cmake_build -DENABLE_PROGRAMS=OFF -DENABLE_TESTING=OFF -DUSE_SHARED_MBEDTLS_LIBRARY=ON \
        -DUSE_STATIC_MBEDTLS_LIBRARY=OFF -DGEN_FILES=OFF
}
# libsrt 1.5.7, ahead of obs-deps' 1.5.2: releases before it have public advisories
# (GHSA-6xg9-784j-24rm, GHSA-4mc6-qmpp-g7gw, GHSA-m96h-3rc9-xx6h). It keeps the
# libsrt.so.1.5 soname and ABI; FFmpeg and OBS's SRT output share this one copy.
srt() {
    tar_src srt https://github.com/Haivision/srt/archive/v1.5.7.tar.gz \
        017cd1e437ef2073a4dd10ddf7b55e86bc3d6ebac0393d13bd22f6a57055d32b
    cmake_build -DENABLE_APPS=OFF -DENABLE_STATIC=OFF -DENABLE_SHARED=ON -DUSE_ENCLIB=mbedtls \
        -DMBEDTLS_PREFIX="$PREFIX"
}
librist() {
    git_src librist https://code.videolan.org/rist/librist.git 809390b3b75a259a704079d0fb4d8f1b5f7fa956
    meson setup build --prefix="$PREFIX" --libdir=lib --buildtype=release -Ddefault_library=shared \
        -Dbuilt_tools=false -Dtest=false -Duse_mbedtls=true
    ninja -C build && ninja -C build install
}
nvcodec() {
    git_src nvcodec https://github.com/ffmpeg/nv-codec-headers.git e844e5b26f46bb77479f063029595293aa8f812d
    make PREFIX="$PREFIX" install
}
ffmpeg() {
    git_src ffmpeg https://github.com/FFmpeg/FFmpeg.git 38b88335f99e76ed89ff3c93f877fdefce736c13
    # A shallow checkout has no tags, so version.sh would name the build after the
    # commit; OBS's FindFFmpeg needs the release number (>= 8.0).
    echo 8.1.2 >VERSION
    # lame has no pkg-config file: FFmpeg finds it (and the others) by path.
    ./configure --prefix="$PREFIX" --enable-shared --disable-static --enable-pic \
        --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib -Wl,-rpath-link,$PREFIX/lib" \
        --enable-version3 --enable-gpl --enable-pthreads \
        --enable-libx264 --enable-libopus --enable-libvorbis --enable-libvpx --enable-libaom \
        --enable-libsvtav1 --enable-libtheora --enable-libmp3lame --enable-librist --enable-libsrt \
        --enable-ffnvcodec --enable-nvenc --enable-nvdec --enable-cuvid \
        --enable-vaapi --enable-vulkan --enable-libdrm \
        --disable-libjack --disable-indev=jack --disable-sdl2 --disable-doc --disable-stripping \
        --disable-programs
    make -j"$JOBS" && make install
}

run_steps ogg vorbis opus vpx svtav1 aom x264 theora lame mbedtls srt librist nvcodec ffmpeg
