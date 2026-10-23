#!/usr/bin/env bash
# Build the Linux tools into /opt/obs-deps/<tool> (bind-mounted from the host's
# out/ by bosn.toml, so the results are on the host), then pack them into dist/.
#   recipes/linux/build.sh [tool...]   (default: every recipes/linux/<tool>.sh)
# A tool is rebuilt only when its recipe (or common.sh) changed since it was
# built: out/<tool>/.recipe-sha256 records what built it.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$(getconf GNU_LIBC_VERSION)" = "glibc 2.28" ] ||
    { echo "error: $(getconf GNU_LIBC_VERSION), expected exactly glibc 2.28" >&2; exit 1; }

all=(headers qrcodegen fdk-aac glib pipewire ffmpeg qt6 libdatachannel libvpl)
tools=("$@")
[ "${#tools[@]}" -gt 0 ] || tools=("${all[@]}")

for tool in "${tools[@]}"; do
    recipe="recipes/linux/$tool.sh"
    [ -f "$recipe" ] || { echo "no recipe $recipe" >&2; exit 1; }
    want="$(cat "$recipe" recipes/linux/common.sh | sha256sum | cut -d' ' -f1)"
    stamp="/opt/obs-deps/$tool/.recipe-sha256"
    if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
        echo "==> $tool: up to date"
        continue
    fi
    echo "==> $tool: building"
    # A tool's directory holds exactly one build: start clean.
    find "/opt/obs-deps/$tool" -mindepth 1 -delete 2>/dev/null || true
    "$recipe"
    echo "$want" >"$stamp"
done

recipes/linux/pack.sh "${tools[@]}"

# Hand everything back to the owner of the checkout (the container runs as root).
owner="$(stat -c %u:%g .)"
chown -R "$owner" /opt/obs-deps dist
