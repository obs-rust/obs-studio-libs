"""Qt 6 is built without GSSAPI, so the AppImage carries no EOL OpenSSL 1.1.1k.

`libQt6Network.so.6` only needs `libgssapi_krb5.so.2` because qtbase's Network
module is configured with the GSSAPI feature on; the AlmaLinux 8 base's krb5
libraries then NEED `libcrypto.so.1.1`, which re-introduces OpenSSL 1.1.1k next
to the pinned 3.5.9. OBS makes no SPNEGO/Negotiate request (update check,
service list, remote text are plain HTTPS), so the auth delegate is dead weight
(obs-rust/obs-studio#2815).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes" / "linux" / "qt6.sh"
BUILD = ROOT / "recipes" / "linux" / "build.sh"


def cmake_flags() -> list[str]:
    return re.findall(r"-D\S+", RECIPE.read_text())


def test_qtbase_is_configured_without_gssapi() -> None:
    flags = cmake_flags()
    assert "-DFEATURE_gssapi=OFF" in flags, (
        "qtbase must not compile the GSSAPI auth delegate: it pulls the base's "
        "krb5 stack, whose libcrypto.so.1.1 is the EOL OpenSSL 1.1.1k"
    )
    assert "-DFEATURE_gssapi=ON" not in flags


def test_qt_still_keeps_the_tls_client_it_needs() -> None:
    flags = cmake_flags()
    # Dropping GSSAPI must not take the HTTPS client with it: QNetworkAccessManager
    # is what the update check, service list and remote-text sources use.
    assert "-DFEATURE_openssl=ON" in flags
    assert "-DFEATURE_openssl_linked=OFF" in flags


def test_build_sh_builds_qt6() -> None:
    match = re.search(r"^all=\((.*)\)$", BUILD.read_text(), re.M)
    assert match, "build.sh must list the default tools"
    assert "qt6" in match[1].split()
