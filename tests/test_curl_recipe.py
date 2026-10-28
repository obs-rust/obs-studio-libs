"""The curl recipe pins a supported libcurl and keeps the AppImage's CA contract.

The AppImage loads libcurl for every update check, service-list fetch and
remote-text load. The AlmaLinux 8 base supplies 7.61.1 (2018, EOL), and the
SRPM rebuild that replaced it (obs-rust/obs-studio#1085) is what carries
`--with-ca-fallback` so HTTPS works on hosts without the RHEL bundle. This
recipe replaces that rebuild, so both properties are pinned here
(obs-rust/obs-studio#2774).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes" / "linux" / "curl.sh"
BUILD = ROOT / "recipes" / "linux" / "build.sh"
SUMMARIES = ROOT / "summaries.json"

# 7.61.1 is the base's; anything below 8.0 is the EOL line this replaces.
EOL_THROUGH = (7, 99, 99)


def version() -> tuple[int, ...]:
    match = re.search(r"^VERSION=(\d+(?:\.\d+)*)$", RECIPE.read_text(), re.M)
    assert match, f"{RECIPE.name} must pin VERSION"
    return tuple(int(part) for part in match[1].split("."))


def test_curl_is_past_the_eol_7_x_line() -> None:
    assert version() > EOL_THROUGH


def test_curl_keeps_the_ca_fallback_and_takes_no_rhel_bundle_path() -> None:
    text = RECIPE.read_text()
    assert "--with-ca-fallback" in text
    # Asserted again at build time against the built library.
    assert "--without-ca-bundle" in text
    assert "--without-ca-path" in text


def test_curl_links_the_pinned_brotli_prefix() -> None:
    # Out of CVE-2026-111497's range (1.0.3-1.2.0); the base's 1.0.6 is not.
    assert "--with-brotli=/opt/obs-deps/brotli" in RECIPE.read_text()


def test_curl_links_the_pinned_openssl_prefix() -> None:
    # curl 8.18+ refuses OpenSSL < 3.0, so the base's 1.1.1k cannot back it,
    # and both prefixes are asserted again against the built library.
    text = RECIPE.read_text()
    assert "--with-openssl=/opt/obs-deps/openssl" in text
    assert "libssl\\.so\\.3" in text


def test_curl_tarball_is_pinned_by_sha256() -> None:
    # tar_src <dir> <url> <sha256>: an unpinned download would drift.
    text = RECIPE.read_text()
    urls = re.findall(r"tar_src\s+\S+\s+(\S+)\s+\\?\s*([0-9a-f]{64})", text)
    assert urls, "the recipe must fetch its source through tar_src with a sha256"
    for url, _ in urls:
        assert url.startswith("https://github.com/curl/curl/releases/download/")


def test_build_sh_builds_dependencies_before_curl() -> None:
    text = BUILD.read_text()
    match = re.search(r"^all=\((.*)\)$", text, re.M)
    assert match, "build.sh must list the default tools"
    tools = match[1].split()
    assert "curl" in tools
    # curl links the pinned brotli and OpenSSL, so both have to exist first.
    assert tools.index("brotli") < tools.index("curl")
    assert tools.index("openssl") < tools.index("curl")


def test_the_catalog_describes_curl() -> None:
    assert "curl" in json.loads(SUMMARIES.read_text())
