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
