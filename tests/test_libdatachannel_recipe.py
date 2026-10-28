"""The libdatachannel recipe links the pinned OpenSSL 3.5.9, not the base's 1.1.1.

libdatachannel is the WebRTC transport behind obs-webrtc's WHIP output, and its
`libdatachannel.so` is the one bundled object in the AppImage that had a
`NEEDED libssl.so.1.1`/`libcrypto.so.1.1` (AlmaLinux 8's EOL 1.1.1k). Even with
the pinned libcurl 8.23.0 and OpenSSL 3.5.9 in the bundle, that single NEEDED
entry kept 1.1.1 in the AppDir, and Qt Network - which `dlopen`s OpenSSL and
takes the first versioned soname it finds - kept speaking 1.1.1
(obs-rust/obs-studio#2774). Two things have to hold, and both are easy to lose
in a recipe edit: the recipe points CMake and pkg-config at the pinned prefix,
and build.sh builds openssl before libdatachannel.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes" / "linux" / "libdatachannel.sh"
BUILD = ROOT / "recipes" / "linux" / "build.sh"
OPENSSL_PREFIX = "/opt/obs-deps/openssl"


def test_recipe_points_cmake_at_the_pinned_openssl_prefix() -> None:
    text = RECIPE.read_text()
    assert f"-DOPENSSL_ROOT_DIR={OPENSSL_PREFIX}" in text
    # pkg-config for anything else that probes OpenSSL through it.
    assert f"{OPENSSL_PREFIX}/lib/pkgconfig" in text


def test_recipe_asserts_the_built_library_uses_openssl_3() -> None:
    # A build that silently falls back to the base image's 1.1.1 must fail here,
    # not ship.
    text = RECIPE.read_text()
    assert "libssl\\.so\\.3" in text
    assert "libssl\\.so\\.1" in text


def test_build_sh_builds_openssl_before_libdatachannel() -> None:
    match = re.search(r"^all=\((.*)\)$", BUILD.read_text(), re.M)
    assert match, "build.sh must list the default tools"
    tools = match[1].split()
    assert "libdatachannel" in tools
    assert "openssl" in tools
    assert tools.index("openssl") < tools.index("libdatachannel")
