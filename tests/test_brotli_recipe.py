"""The brotli recipe stays past CVE-2026-111497's vulnerable range.

The AppImage's libcurl decodes with brotli, and the AlmaLinux 8 base's 1.0.6 is
inside the vulnerable 1.0.3-1.2.0 range. Until this recipe's release ships in
the AppImage, obs-rust/obs-studio#2211's outgoing-HTTP stop-gap cannot be
reverted (obs-rust/obs-studio#2774).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes" / "linux" / "brotli.sh"
BUILD = ROOT / "recipes" / "linux" / "build.sh"

# The first release past CVE-2026-111497's range.
VULNERABLE_THROUGH = (1, 2, 0)


def version() -> tuple[int, ...]:
    match = re.search(r"^VERSION=(\d+(?:\.\d+)*)$", RECIPE.read_text(), re.M)
    assert match, f"{RECIPE.name} must pin VERSION"
    return tuple(int(part) for part in match[1].split("."))


def test_brotli_is_past_the_vulnerable_range() -> None:
    assert version() > VULNERABLE_THROUGH


def test_brotli_builds_shared_libraries_without_its_tests() -> None:
    text = RECIPE.read_text()
    # cmake_build already asks for BUILD_SHARED_LIBS=ON; the codec's own test
    # binaries are not needed in a dependency artifact.
    assert "cmake_build -DBROTLI_DISABLE_TESTS=ON" in text


def test_build_sh_builds_brotli_by_default() -> None:
    text = BUILD.read_text()
    match = re.search(r"^all=\((.*)\)$", text, re.M)
    assert match, "build.sh must list the default tools"
    assert "brotli" in match[1].split()
