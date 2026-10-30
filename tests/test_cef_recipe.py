"""The CEF recipe keeps line tables in libcef.so.

obs-studio's Flatpak qualification (ci/flatpak_runtime.py) resolves
`info line cef_version_info` through the Debug extension. symbol_level=0 drops
all DWARF, so GDB finds no line information; symbol_level=1 keeps line tables
at a fraction of full debug info (obs-rust/obs-studio#2363).
"""

from __future__ import annotations

import re
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1] / "recipes" / "cef" / "linux" / "build.sh"
MAC = Path(__file__).resolve().parents[1] / "recipes" / "cef" / "macos" / "build.sh"

# The Linux 8078 archive (obs-rust/cef release 8078) was built from this commit.
MAC_CHECKOUT = "426920c33ef22551e0b8f48cf343d623ac25642d"
MAC_SANDBOX = "Chromium Embedded Framework.framework/Libraries/libcef_sandbox.dylib"


def gn_defines(path: Path) -> list[str]:
    defines = re.search(r'^export GN_DEFINES="([^"]*)"', path.read_text(), re.M)
    assert defines, f"{path.name} must export GN_DEFINES"
    return defines[1].split()


def test_cef_keeps_line_tables() -> None:
    assert "symbol_level=1" in gn_defines(BUILD)


def test_macos_recipe_pins_codecs_and_the_sandbox_library() -> None:
    """macOS pages need H.264/AAC, and the helper needs the sandbox library.

    obs-rust/obs-studio#2418. The archive is the Linux build's commit, and
    pack refuses a tree that has no libcef_sandbox.dylib in the framework.
    """
    text = MAC.read_text()
    flags = gn_defines(MAC)
    for flag in (
        "is_official_build=true",
        "proprietary_codecs=true",
        "ffmpeg_branding=Chrome",
        "symbol_level=1",
        "chrome_pgo_phase=0",
    ):
        assert flag in flags
    assert "use_sysroot=true" not in flags
    assert MAC_CHECKOUT in text
    assert MAC_SANDBOX in text
    assert "--arm64-build" in text
    assert "--x64-build" in text
    assert "--build-target=cefclient" in text
    # An arm64 Mac's hook writes only Release_GN_arm64 unless this is set,
    # and GN_OUT_CONFIGS keeps the other arch's out directory from returning.
    assert "CEF_ENABLE_AMD64=1" in text
    assert "GN_OUT_CONFIGS=Release_GN_x64" in text
    assert "GN_OUT_CONFIGS=Release_GN_arm64" in text


def test_linux_recipe_builds_arm64() -> None:
    """The arm64 archive is the same recipe with `target_cpu="arm64"`.

    obs-rust/obs-studio#3062: ubuntu-aarch64 still pins CEF 7871, so the nightly
    version guard fails on it. The Linux recipe used to hardcode the x86_64
    automated build, the x64 out directory and the `linux64` distribution, so
    nothing but x86_64 could be produced; x86_64 stays the default argument.
    """
    text = BUILD.read_text()
    assert "--x64-build" in text
    assert "--arm64-build" in text
    # The host is x86_64, so an arm64 run must ask GN for arm64 explicitly.
    assert 'target_cpu=\\"arm64\\"' in text or "target_cpu=" in text
    assert "Release_GN_arm64" in text
    assert "linuxarm64" in text
    # obs-studio's pin (ci/test_cef_pin.py) names the archive _linux_aarch64.
    assert "aarch64" in text
    assert "cef_binary_${VERSION}_linux_${asset_arch}" in text
