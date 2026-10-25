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


def test_cef_keeps_line_tables() -> None:
    defines = re.search(r'^export GN_DEFINES="([^"]*)"', BUILD.read_text(), re.M)
    assert defines, "build.sh must export GN_DEFINES"
    assert "symbol_level=1" in defines[1].split()
