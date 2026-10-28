#!/usr/bin/env bash
# curl 8.23.0 for os=linux,arch=x86_64,libc=glibc,os_version=2.28 (obs-studio-libs).
# libcurl is what every AppImage user's update check, service-list fetch and
# remote-text load goes through; the AlmaLinux 8 base supplies 7.61.1 (2018,
# EOL), which obs-rust/obs-studio#2774 replaces with a pinned build of this
# recipe. Two properties must survive from the SRPM rebuild it replaces
# (obs-rust/obs-studio#1085):
#   * --with-ca-fallback, so libcurl uses OpenSSL's default verify paths and
#     honours the SSL_CERT_FILE that AppRun points at the host's bundle,
#     instead of the RHEL-only /etc/pki/tls/certs/ca-bundle.crt (absent on
#     Debian/Ubuntu/Arch hosts);
#   * brotli support, decoded by the pinned 1.2.1 (out of CVE-2026-111497's
#     range) rather than the base's 1.0.6, so it is linked against that prefix
#     explicitly (recipes/linux/brotli.sh) and never against the base's copy.
# TLS is the pinned OpenSSL 3.5.9 (recipes/linux/openssl.sh): curl 8.18+
# refuses anything older than 3.0, so the base's EOL 1.1.1k cannot back it.
PREFIX=/opt/obs-deps/curl
VERSION=8.23.0
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

curl_build() {
    tar_src curl https://github.com/curl/curl/releases/download/curl-8_23_0/curl-8.23.0.tar.gz \
        e3de77cfa6367083c776a26647fc9f633b538c06c3baa73d931a252ac8f72b49
    autotools \
        --with-openssl=/opt/obs-deps/openssl \
        --with-brotli=/opt/obs-deps/brotli \
        --with-zlib \
        --with-ca-fallback \
        --without-ca-bundle \
        --without-ca-path \
        --without-libpsl \
        --without-libidn2 \
        --without-nghttp2 \
        --without-nghttp3 \
        --without-ngtcp2 \
        --disable-ldap \
        --disable-ldaps \
        --disable-manual \
        --disable-rtsp \
        --disable-dict \
        --disable-telnet \
        --disable-tftp \
        --disable-pop3 \
        --disable-imap \
        --disable-smtp \
        --disable-gopher \
        --disable-mqtt
    # The two properties the AppImage depends on, asserted at build time: no
    # RHEL CA path compiled in, and brotli decoded by the pinned prefix.
    ! grep -a -q '/etc/pki/tls/certs/ca-bundle.crt' "$PREFIX"/lib/libcurl.so* ||
        { echo "error: libcurl still carries the RHEL CA bundle path" >&2; exit 1; }
    LD_LIBRARY_PATH="/opt/obs-deps/openssl/lib:/opt/obs-deps/brotli/lib:$PREFIX/lib" \
        ldd "$PREFIX"/lib/libcurl.so.4 >"$work/ldd.txt"
    grep -q '/opt/obs-deps/brotli/lib/libbrotli' "$work/ldd.txt" ||
        { echo "error: libcurl does not link the pinned brotli prefix" >&2; exit 1; }
    grep -q '/opt/obs-deps/openssl/lib/libssl\.so\.3' "$work/ldd.txt" ||
        { echo "error: libcurl does not link the pinned OpenSSL 3 prefix" >&2; exit 1; }
    # curl_version() is the string the AppImage's verification reads.
    printf '%s\n' '#include <stdio.h>' '#include <curl/curl.h>' \
        'int main(void) { puts(curl_version()); return 0; }' >"$work/curl-version.c"
    cc "$work/curl-version.c" -I"$PREFIX/include" \
        -L"$PREFIX/lib" -L/opt/obs-deps/openssl/lib -L/opt/obs-deps/brotli/lib \
        -lcurl -lssl -lcrypto \
        -Wl,-rpath,"$PREFIX/lib" -o "$work/curl-version"
    LD_LIBRARY_PATH="/opt/obs-deps/openssl/lib:/opt/obs-deps/brotli/lib:$PREFIX/lib" \
        "$work/curl-version"
}

run_steps curl_build
