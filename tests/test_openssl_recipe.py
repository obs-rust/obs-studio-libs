"""The pinned libcurl's TLS runtime is OpenSSL 3.5 LTS, not the base's 1.1.1k.

curl 8.18 and later refuse OpenSSL older than 3.0, so the AlmaLinux 8 base's
1.1.1k (EOL) cannot back a pinned libcurl. The prefix is deliberately kept off
the image's CMake/pkg-config path: the rest of the tree still consumes the
base's 1.1.1k, and re-pointing all of it is a separate unit
(obs-rust/obs-studio#2774).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes" / "linux" / "openssl.sh"
BUILD = ROOT / "recipes" / "linux" / "build.sh"
SUMMARIES = ROOT / "summaries.json"

# curl's own floor for the pinned libcurl (recipes/linux/curl.sh).
OPENSSL_FLOOR = (3, 0, 0)


def version() -> tuple[int, ...]:
    match = re.search(r"^VERSION=(\d+(?:\.\d+)*)$", RECIPE.read_text(), re.M)
    assert match, f"{RECIPE.name} must pin VERSION"
    return tuple(int(part) for part in match[1].split("."))


def test_openssl_is_new_enough_for_the_pinned_curl() -> None:
    assert version() >= OPENSSL_FLOOR


def test_openssl_installs_a_shared_runtime_without_a_test_suite() -> None:
    text = RECIPE.read_text()
    assert "shared" in text
    assert "no-tests" in text
    assert "--libdir=lib" in text


def test_openssl_tarball_is_pinned_by_sha256() -> None:
    urls = re.findall(
        r"tar_src\s+\S+\s+(\S+)\s+\\?\s*([0-9a-f]{64})", RECIPE.read_text()
    )
    assert urls, "the recipe must fetch its source through tar_src with a sha256"
    for url, _ in urls:
        assert url.startswith("https://github.com/openssl/openssl/releases/download/")


def test_build_sh_builds_openssl_before_curl() -> None:
    match = re.search(r"^all=\((.*)\)$", BUILD.read_text(), re.M)
    assert match, "build.sh must list the default tools"
    tools = match[1].split()
    assert "openssl" in tools
    # curl's --with-openssl points at the prefix, so it has to exist first.
    assert tools.index("openssl") < tools.index("curl")


def test_the_catalog_describes_openssl() -> None:
    assert "openssl" in json.loads(SUMMARIES.read_text())
