#!/usr/bin/env python3
"""Package soldr's xwin payload as the Windows toolchain zip depot_tools wants.

obs-rust/obs-studio#2417. A Linux->Windows CEF build does not use a Windows
install: Chromium's `build/vs_toolchain.py` downloads a toolchain archive from
`DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL`, keyed by a sha1 of the tree
(`win_toolchain/get_toolchain_if_necessary.py`), and Google's own archive is
internal. `package_from_installed.py` is the same idea on Windows; this is its
Linux counterpart for `soldr cc --print-sysroot --target <triple>`, whose xwin
payload carries the MSVC STL and Windows SDK headers and libs for both
architectures.

What it does, per `package_from_installed.py`:

    crt/include                        -> VC/Tools/MSVC/<msvc>/include
    crt/lib/{x86_64,aarch64}           -> VC/Tools/MSVC/<msvc>/lib/{x64,arm64}
    sdk/include/{um,ucrt,shared,winrt,cppwinrt}
                                       -> Windows Kits/10/Include/<sdk>/<dir>
    sdk/lib/{um,ucrt}/<xwin arch>      -> Windows Kits/10/Lib/<sdk>/{um,ucrt}/<arch>
    VS_VERSION                         -> "2026" (what depot_tools compares)

The files are hardlinked (copied across filesystems): depot_tools hashes with
`os.walk`, which does not follow symlinked directories, so a symlink farm would
hash as empty and the download would be renamed as corrupt.

Not packaged, because the payload does not carry them: `cl.exe`/`link.exe`
(Chromium builds with clang-cl and lld-link), `atlmfc`, and the SDK `bin`
tools the Windows-only SetEnv scripts use. `ciopfs` supplies the
case-insensitive view of the extracted tree on Linux.

usage:
  package_win_toolchain.py package --xwin DIR --out DIR
      [--msvc 14.50.35717] [--sdk 10.0.26100] [--vs-version 2026]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

# Windows arch directory names as depot_tools and MSBuild spell them.
XWIN_ARCH = {"x64": "x86_64", "arm64": "aarch64"}
SDK_INCLUDE_DIRS = ("um", "ucrt", "shared", "winrt", "cppwinrt")
SDK_LIB_DIRS = ("um", "ucrt")
# build/vs_toolchain.py's TOOLCHAIN_HASH for the Chromium revision CEF 8078
# syncs; the override variable is GYP_MSVS_HASH_<hash>.
CHROMIUM_TOOLCHAIN_HASH = "3bfcb536c8"
# A zip entry timestamp that does not depend on when the package ran, so the
# archive (and its hash) is reproducible.
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _link_or_copy(src: str, dst: str) -> str:
    try:
        os.link(src, dst)
    except OSError:
        return shutil.copy2(src, dst)
    return dst


def materialize(
    xwin: Path,
    dest: Path,
    *,
    msvc_version: str,
    sdk_version: str,
    vs_version: str,
) -> Path:
    """Build the toolchain tree `dest` from the xwin payload `xwin`."""
    vc = dest / "VC" / "Tools" / "MSVC" / msvc_version
    sdk = dest / "Windows Kits" / "10"
    pairs: list[tuple[Path, Path]] = [(xwin / "crt" / "include", vc / "include")]
    pairs.extend((xwin / "sdk" / "include" / name, sdk / "Include" / sdk_version / name) for name in SDK_INCLUDE_DIRS)
    for arch, xwin_arch in XWIN_ARCH.items():
        pairs.append((xwin / "crt" / "lib" / xwin_arch, vc / "lib" / arch))
        pairs.extend(
            (xwin / "sdk" / "lib" / name / xwin_arch, sdk / "Lib" / sdk_version / name / arch) for name in SDK_LIB_DIRS
        )
    missing = [str(src) for src, _ in pairs if not src.is_dir()]
    if missing:
        message = "xwin payload is missing: " + ", ".join(missing)
        raise FileNotFoundError(message)
    dest.mkdir(parents=True, exist_ok=True)
    for src, dst in pairs:
        shutil.copytree(src, dst, copy_function=_link_or_copy, dirs_exist_ok=True)
    (dest / "VS_VERSION").write_text(vs_version + "\n")
    return dest


def _file_order(root: Path) -> list[tuple[str, Path]]:
    """Relative paths in depot_tools' order: lower cased, backslash separated.

    `GetFileList` sorts on `str.replace('/', '\\\\').lower()`, and `CalculateHash`
    hashes exactly that string followed by the file's bytes.
    """
    entries = []
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix().replace("/", "\\").lower()
            entries.append((relative, path))
    return sorted(entries, key=lambda item: item[0])


# CalculateHash hashes `path_without_hash`, and on the install side that string
# keeps the `vs_files` component (it strips the hash directory, not the install
# root), so every entry carries this prefix. Measured against depot_tools'
# get_toolchain_if_necessary.py: dropping it names the zip one sha1, and
# installing it rejects that name as corrupt.
HASH_PATH_PREFIX = "vs_files\\"


def tree_sha1(root: Path) -> str:
    """The toolchain hash depot_tools keys `<sha1>.zip` on."""
    digest = hashlib.sha1()
    for relative, path in _file_order(root):
        digest.update((HASH_PATH_PREFIX + relative).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_zip(root: Path, zip_path: Path) -> None:
    """Archive `root`'s contents (no wrapping directory), reproducibly."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for _, path in _file_order(root):
            # The hash key is lower cased; the archive keeps the real names,
            # because extraction happens on a case-insensitive mount but the
            # names still have to read back as the SDK spells them.
            name = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())


def package(
    xwin: Path,
    out: Path,
    *,
    msvc_version: str,
    sdk_version: str,
    vs_version: str,
) -> tuple[Path, str]:
    """Materialize, hash, and zip the toolchain; returns (zip, sha1)."""
    tree = out / f"toolchain-{msvc_version}-{sdk_version}"
    materialize(xwin, tree, msvc_version=msvc_version, sdk_version=sdk_version, vs_version=vs_version)
    digest = tree_sha1(tree)
    zip_path = out / f"{digest}.zip"
    write_zip(tree, zip_path)
    (out / "toolchain.json").write_text(
        json.dumps(
            {
                "path": str(tree),
                "version": vs_version,
                "msvc": msvc_version,
                "sdk": sdk_version,
                "sha1": digest,
                "zip": str(zip_path),
                "chromium_toolchain_hash": CHROMIUM_TOOLCHAIN_HASH,
            },
            indent=2,
        )
        + "\n"
    )
    return zip_path, digest


def shell_exports(out: Path, digest: str) -> str:
    """The environment a cross build needs to pick up the packaged toolchain."""
    return "\n".join(
        [
            f'export DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL="file://{out}"',
            "export DEPOT_TOOLS_WIN_TOOLCHAIN=1",
            f"export GYP_MSVS_HASH_{CHROMIUM_TOOLCHAIN_HASH}={digest}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    package_parser = sub.add_parser("package", help="materialize, hash and zip the toolchain")
    package_parser.add_argument("--xwin", type=Path, required=True)
    package_parser.add_argument("--out", type=Path, required=True)
    package_parser.add_argument("--msvc", default="14.50.35717")
    package_parser.add_argument("--sdk", default="10.0.26100")
    package_parser.add_argument("--vs-version", default="2026")
    args = parser.parse_args(argv)

    try:
        zip_path, digest = package(
            args.xwin,
            args.out,
            msvc_version=args.msvc,
            sdk_version=args.sdk,
            vs_version=args.vs_version,
        )
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"toolchain zip: {zip_path}")
    print(f"toolchain sha1: {digest}")
    print(shell_exports(args.out, digest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
