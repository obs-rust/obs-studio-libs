"""The Windows CEF archive is cross-built from Linux, so its recipe and its
Windows toolchain package are repo artefacts, not a Windows host.

obs-rust/obs-studio#2417: CEF's `automate-git.py` on branch 8078 has no
target-OS switch (only `--x64-build` / `--arm64-build`), so a Windows build
cannot ride the Linux recipe's sync/build steps. It needs its own GN invocation
with `target_os="win"` and a depot_tools win_toolchain zip; soldr's xwin payload
(soldr 0.9.48) supplies the MSVC/Windows SDK headers and libs for both
architectures, but nothing turns it into that zip yet.

The packaging half is testable here: the layout, the archive naming and the
tree hash depot_tools keys the download on.
"""

from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "recipes" / "cef" / "windows"
BUILD = WINDOWS / "build.sh"
PACKAGE = WINDOWS / "package_win_toolchain.py"
BOSN = ROOT / "bosn.toml"

MSVC = "14.50.35717"
SDK = "10.0.26100"


def load_package_module():
    spec = importlib.util.spec_from_file_location("package_win_toolchain", PACKAGE)
    assert spec and spec.loader, f"missing {PACKAGE}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def xwin(tmp_path: Path) -> Path:
    """A stand-in for `soldr cc --print-sysroot`'s xwin payload."""
    root = tmp_path / "xwin"
    for arch in ("x86_64", "aarch64"):
        (root / "crt" / "lib" / arch).mkdir(parents=True)
        (root / "crt" / "lib" / arch / "libcmt.lib").write_bytes(arch.encode())
        (root / "sdk" / "lib" / "um" / arch).mkdir(parents=True)
        (root / "sdk" / "lib" / "um" / arch / "kernel32.lib").write_bytes(arch.encode())
        (root / "sdk" / "lib" / "ucrt" / arch).mkdir(parents=True)
        (root / "sdk" / "lib" / "ucrt" / arch / "ucrt.lib").write_bytes(arch.encode())
    (root / "crt" / "include").mkdir(parents=True)
    (root / "crt" / "include" / "vector").write_text("// MSVC STL\n")
    for sdk_dir in ("um", "ucrt", "shared", "winrt", "cppwinrt"):
        (root / "sdk" / "include" / sdk_dir).mkdir(parents=True)
        (root / "sdk" / "include" / sdk_dir / "windows.h").write_text(sdk_dir)
    (root / "sdk" / "include" / SDK).mkdir(parents=True)
    return root


def test_windows_recipe_exists_and_is_step_split() -> None:
    assert BUILD.is_file(), f"{BUILD} must exist (#2417)"
    assert BUILD.stat().st_mode & 0o111, "build.sh must be executable"
    text = BUILD.read_text()
    assert "sync|toolchain|build|pack" in text
    # A Windows cross build cannot use automate's build step, and the arm64
    # runs died as bosn `cancelled` when they rode a tick, so the recipe is
    # split and each step resumes.
    for step in ("sync)", "build)", "pack)"):
        assert step in text, step


def test_windows_recipe_pins_the_codecs_and_target_os() -> None:
    text = BUILD.read_text()
    for flag in (
        "is_official_build=true",
        "proprietary_codecs=true",
        "ffmpeg_branding=Chrome",
        "symbol_level=1",
        "chrome_pgo_phase=0",
    ):
        assert flag in text, flag
    # The host is Linux: nothing else selects the Windows target.
    assert 'target_os=\\"win\\"' in text or 'target_os="win"' in text
    assert "Release_GN_x64" in text
    assert "Release_GN_arm64" in text
    assert "windows64" in text
    assert "windowsarm64" in text
    # obs-studio's pin (ci/test_cef_pin.py) names the archives
    # cef_binary_8078_windows_{x64,arm64}.zip.
    assert "cef_binary_${VERSION}_windows_${arch}" in text
    assert "x64)" in text and "arm64)" in text


def test_windows_recipe_points_depot_tools_at_the_packaged_toolchain() -> None:
    text = BUILD.read_text()
    # build/vs_toolchain.py keys the download on TOOLCHAIN_HASH and only takes
    # an override through GYP_MSVS_HASH_<hash>.
    assert "GYP_MSVS_HASH_" in text
    assert "DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL" in text
    assert "DEPOT_TOOLS_WIN_TOOLCHAIN=1" in text
    # On Linux the toolchain dir has to be case-insensitive (ciopfs), or
    # clang's #pragma once and -Wnonportable-include-path break.
    assert "ciopfs" in text
    assert "package_win_toolchain.py" in text


def test_bosn_has_the_windows_tasks() -> None:
    manifest = BOSN.read_text()
    for task in ("cef-win-sync", "cef-win-build", "cef-win-pack"):
        assert f"[task.{task}]" in manifest, task


def test_toolchain_layout_matches_depot_tools(xwin: Path, tmp_path: Path) -> None:
    """`package_from_installed.py` copy list, rebuilt from the xwin payload."""
    module = load_package_module()
    dest = module.materialize(xwin, tmp_path / "toolchain", msvc_version=MSVC, sdk_version=SDK, vs_version="2026")

    vc = dest / "VC" / "Tools" / "MSVC" / MSVC
    sdk = dest / "Windows Kits" / "10"
    for path in (
        vc / "include" / "vector",
        vc / "lib" / "x64" / "libcmt.lib",
        vc / "lib" / "arm64" / "libcmt.lib",
    ):
        assert path.is_file(), path
    for sdk_dir in ("um", "ucrt", "shared", "winrt", "cppwinrt"):
        assert (sdk / "Include" / SDK / sdk_dir / "windows.h").is_file(), sdk_dir
    for arch in ("x64", "arm64"):
        assert (sdk / "Lib" / SDK / "um" / arch / "kernel32.lib").is_file(), arch
        assert (sdk / "Lib" / SDK / "ucrt" / arch / "ucrt.lib").is_file(), arch
    # depot_tools reads VS_VERSION to decide whether the toolchain is current.
    assert (dest / "VS_VERSION").read_text().strip() == "2026"
    # The toolchain dir must be real files, not symlinked directories: os.walk
    # does not follow them, so the tree hash would come out empty.
    assert not (vc / "include").is_symlink()


def test_tree_hash_matches_depot_tools_and_names_the_zip(xwin: Path, tmp_path: Path) -> None:
    """`<sha1>.zip` is the download name, and the hash is over the files.

    get_toolchain_if_necessary.CalculateHash hashes each relative path (lower
    cased, backslashes) followed by the file's bytes.
    """
    module = load_package_module()
    dest = module.materialize(xwin, tmp_path / "toolchain", msvc_version=MSVC, sdk_version=SDK, vs_version="2026")
    first = module.tree_sha1(dest)
    assert len(first) == 40 and first == first.lower()
    assert module.tree_sha1(dest) == first

    # depot_tools hashes the path with a `vs_files` prefix, not the bare one:
    # measured against get_toolchain_if_necessary.py, which strips the hash
    # directory and keeps the install root.
    reference = hashlib.sha1()
    for key, file in sorted(
        (("vs_files\\" + item.relative_to(dest).as_posix().replace("/", "\\")).lower(), item)
        for item in dest.rglob("*")
        if item.is_file()
    ):
        reference.update(key.encode())
        reference.update(file.read_bytes())
    assert reference.hexdigest() == first

    zip_path, digest = module.package(xwin, tmp_path / "out", msvc_version=MSVC, sdk_version=SDK, vs_version="2026")
    assert zip_path.name == f"{digest}.zip"
    assert digest == first
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "VS_VERSION" in names
    assert f"Windows Kits/10/Include/{SDK}/um/windows.h" in names

    # A change inside the payload must move the name, or depot_tools would keep
    # serving a stale cached toolchain under the old hash.
    (xwin / "crt" / "include" / "vector").write_text("// MSVC STL v2\n")
    other = module.materialize(xwin, tmp_path / "toolchain2", msvc_version=MSVC, sdk_version=SDK, vs_version="2026")
    assert module.tree_sha1(other) != first


def test_toolchain_hash_is_the_one_chromium_asks_for() -> None:
    """build/vs_toolchain.py maps GYP_MSVS_HASH_<TOOLCHAIN_HASH> to our zip.

    TOOLCHAIN_HASH is a constant of the Chromium revision CEF 8078 syncs, so the
    recipe has to name the same override variable or depot_tools downloads
    Google's internal package (which nobody here can reach).
    """
    text = BUILD.read_text()
    assert "GYP_MSVS_HASH_3bfcb536c8" in text or "GYP_MSVS_HASH_${" in text
