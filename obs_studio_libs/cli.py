"""obs-studio-libs: pack, ingest and catalog prebuilt dependencies (zackees/manifest.json).

    obs-studio-libs pack   <dir> --tool qt6 --version 6.11.1 \
        --platform os=linux,arch=x86_64,libc=glibc,os_version=2.28 [--variant ..] [--label ..] --out dist
    obs-studio-libs ingest <forge-artifact.tar.gz> --tool qt6 --version 6.11.1 --platform ... --out dist
    obs-studio-libs add    dist/*.tar.zst.json --assets <assets-branch checkout> [--replace]
    obs-studio-libs slice  --assets <dir> --tool qt6 --version 6.11.1 --platform os=linux,arch=x86_64 -o slice.json
    obs-studio-libs fetch  --lock deps.lock.json [--only qt6]

The catalogs live on the orphan `assets` branch: manifest.json at its root
(the Index) and <tool>/manifest.json per tool, as in zackees/soldr-toolchain.
Archives are release assets `<tool>-<version>-<platform>.tar.zst` (zstd 9).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import catalog as cat
from .fetch import Pin, install_all
from .model import ManifestError, Platform, Variant, dumps, parse_lock, parse_record, parse_summaries
from .pack import ingest, pack

ROOT = Path(__file__).resolve().parents[1]


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tool", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--platform", required=True, help="os=..,arch=..[,os_version=..][,libc=..][,abi=..]")
    p.add_argument("--variant", default="", help="[optimization=..][,edition=..][,flavor=..]")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="obs-studio-libs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("pack", "ingest"):
        s = sub.add_parser(name)
        s.add_argument("source", type=Path)
        _common(s)
        s.add_argument("--label", default="", help="build label for a rebuild of a published version")
        s.add_argument("--out", type=Path, default=Path("dist"))
    s = sub.add_parser("add")
    s.add_argument("records", type=Path, nargs="+")
    s.add_argument("--assets", type=Path, required=True)
    s.add_argument("--replace", action="store_true", help="allow new bytes under a published filename")
    s = sub.add_parser("slice")
    _common(s)
    s.add_argument("--assets", type=Path, required=True)
    s.add_argument("-o", "--output", type=Path, required=True)
    s = sub.add_parser("fetch", help="install every pin of a lock file (or --only some tools)")
    s.add_argument("--lock", type=Path, required=True)
    s.add_argument("--only", action="append", default=[])
    args = p.parse_args(argv)

    try:
        if args.cmd in ("pack", "ingest"):
            fn = pack if args.cmd == "pack" else ingest
            record = fn(
                args.source,
                args.tool,
                args.version,
                Platform.from_spec(args.platform),
                Variant.from_spec(args.variant),
                args.out,
                args.label,
            )
            a = record.entry.asset
            print(f"{args.out / a.filename}: {a.size_bytes} bytes, sha256 {a.sha256}")
        elif args.cmd == "add":
            summaries = parse_summaries((ROOT / "summaries.json").read_bytes())
            for path in args.records:
                record = parse_record(path.read_bytes(), str(path))
                current = cat.load_catalog(args.assets, record.tool)
                cat.write_catalog(args.assets, cat.add_platform(current, record.version, record.entry, args.replace))
                print(f"{record.tool}/manifest.json: {record.version} {record.entry.platform.flat()}")
            cat.write_index(args.assets, summaries)
        elif args.cmd == "slice":
            sl = cat.make_slice(
                args.assets, args.tool, args.version, Platform.from_spec(args.platform), Variant.from_spec(args.variant)
            )
            args.output.write_text(dumps(sl))
            print(f"{args.output}: {sl.asset.filename}")
        elif args.cmd == "fetch":
            lock = parse_lock(args.lock.read_bytes(), str(args.lock))
            chosen = [t for t in lock.tools if not args.only or t.tool in args.only]
            jobs = [(Pin(t.tool, t.version, t.platform, t.variant, t.sha256), Path(t.install)) for t in chosen]
            for locked, asset in zip(chosen, install_all(jobs, lock.root), strict=True):
                print(f"{asset.filename} -> {locked.install}")
    except ManifestError as e:
        print(f"obs-studio-libs: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
