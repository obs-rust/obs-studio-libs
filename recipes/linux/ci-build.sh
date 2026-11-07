#!/usr/bin/env bash
# Dispatch counterpart of bosn.toml's linux stack, limited to FFmpeg initially.
set -euo pipefail
mode="${1:?check or build}"
tool="${2:?tool}"
version="${3:?version}"
label="${4-}"
source_dir="$(realpath "${5:-.}")"
[[ "$mode" = check || "$mode" = build ]] || exit 1
[[ "$tool" = ffmpeg ]] || { echo 'Only ffmpeg is supported' >&2; exit 1; }
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
[[ -z "$label" || "$label" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || exit 1
recipe="$source_dir/recipes/linux/$tool.sh"
actual="$(sed -n 's/^VERSION=//p' "$recipe")"
[[ "$actual" = "$version" ]] || { echo "Recipe builds $actual, requested $version" >&2; exit 1; }
[[ "$mode" = build ]] || exit 0
mkdir -p "$source_dir/out"
docker build --tag obs-libs-linux --file "$source_dir/recipes/linux/Dockerfile" "$source_dir"
# These are the linux stack's exact mount destinations and working directory.
# Fresh hosted runner: no producer cache or other tools' prefixes are reused.
docker run --rm --workdir /src \
    --mount "type=bind,source=$source_dir,destination=/src" \
    --mount "type=bind,source=$source_dir/out,destination=/opt/obs-deps" \
    --env UV_CACHE_DIR=/tmp/uv-cache --env UV_PROJECT_ENVIRONMENT=/tmp/uv-venv \
    obs-libs-linux bash -euo pipefail -c '
        recipes/linux/ffmpeg.sh
        cat recipes/linux/ffmpeg.sh recipes/linux/common.sh | sha256sum | cut -d" " -f1 > /opt/obs-deps/ffmpeg/.recipe-sha256
    '
uv run obs-studio-libs pack "$source_dir/out/ffmpeg" --tool "$tool" --version "$version" \
    --platform os=linux,arch=x86_64,libc=glibc,os_version=2.28 \
    --variant optimization=release --label "$label" --out dist
