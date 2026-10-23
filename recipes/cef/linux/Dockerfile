# Build environment for CEF on os=linux,arch=x86_64 (obs-rust/obs-studio#1864).
# Chromium's build wants a Debian/Ubuntu host; the result links against
# Chromium's own Debian sysroot (use_sysroot=true), not this image's glibc, so
# the host does not set the artifact's glibc floor (measured by pack). The
# Chromium build dependencies are installed by the recipe from the checked-out
# source (install-build-deps.sh), since they are versioned with it.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 python3-venv lsb-release sudo file xz-utils \
        cmake ninja-build build-essential binutils \
 && rm -rf /var/lib/apt/lists/*
RUN git config --system --add safe.directory '*'
