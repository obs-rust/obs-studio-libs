"""pack -> add -> root Index -> resolve, on real files, checked by manifest.json's own validator."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from manifest_json import validate_document

from obs_studio_libs import catalog as cat
from obs_studio_libs.model import (
    ManifestError,
    Platform,
    Summaries,
    Variant,
    parse_catalog,
    parse_index,
    parse_record,
)
from obs_studio_libs.pack import measure_floor, pack

LINUX = Platform.from_spec("os=linux,arch=x86_64,libc=glibc,os_version=2.28")
NONE = Variant()


def tree(tmp: Path, text: str = "hello") -> Path:
    d = tmp / "src"
    (d / "lib").mkdir(parents=True)
    (d / "lib" / "a.txt").write_text(text)
    (d / "link").symlink_to("lib/a.txt")
    return d


def test_pack_names_and_records(tmp_path):
    rec = pack(tree(tmp_path), "demo", "1.0", LINUX, NONE, tmp_path / "dist")
    assert rec.entry.asset.filename == "demo-1.0-linux-x86_64-glibc2.28.tar.zst"
    assert rec.entry.asset.urls == (
        "https://github.com/obs-rust/obs-studio-libs/releases/download/demo-1.0/demo-1.0-linux-x86_64-glibc2.28.tar.zst",
    )
    again = parse_record((tmp_path / "dist" / f"{rec.entry.asset.filename}.json").read_bytes())
    assert again == rec


def test_add_writes_a_valid_root_index_and_catalog(tmp_path):
    rec = pack(tree(tmp_path), "demo", "1.0", LINUX, NONE, tmp_path / "dist")
    assets = tmp_path / "assets"
    assets.mkdir()
    cat.write_catalog(assets, cat.add_platform(cat.load_catalog(assets, "demo"), rec.version, rec.entry))
    cat.write_index(assets, Summaries((("demo", "demo tool"),)))
    for doc in (assets / "manifest.json", assets / "demo" / "manifest.json"):
        validate_document(json.loads(doc.read_text()))
    index = parse_index((assets / "manifest.json").read_bytes())
    entry = index.tool("demo")
    assert entry is not None and entry.descriptor.url == "demo/manifest.json"  # relative, as soldr-toolchain
    got = cat.resolve(
        index,
        "demo",
        "latest-stable",
        Platform.from_spec("os=linux,arch=x86_64"),
        NONE,
        lambda rel: (assets / rel).read_bytes(),
    )
    assert got == rec.entry.asset


def test_published_bytes_are_immutable(tmp_path):
    first = pack(tree(tmp_path, "one"), "demo", "1.0", LINUX, NONE, tmp_path / "d1")
    catalog = cat.add_platform(cat.empty_catalog("demo"), "1.0", first.entry)
    (tmp_path / "src").rename(tmp_path / "old")
    second = pack(tree(tmp_path, "two"), "demo", "1.0", LINUX, NONE, tmp_path / "d2")
    with pytest.raises(ManifestError, match="immutable"):
        cat.add_platform(catalog, "1.0", second.entry)
    relabeled = pack(tmp_path / "src", "demo", "1.0", LINUX, NONE, tmp_path / "d3", label="rebuild1")
    both = cat.add_platform(catalog, "1.0", relabeled.entry)
    assert both.release("1.0") is not None


def test_a_tampered_catalog_is_refused(tmp_path):
    rec = pack(tree(tmp_path), "demo", "1.0", LINUX, NONE, tmp_path / "dist")
    assets = tmp_path / "assets"
    assets.mkdir()
    cat.write_catalog(assets, cat.add_platform(cat.empty_catalog("demo"), "1.0", rec.entry))
    index = cat.write_index(assets, Summaries(()))
    (assets / "demo" / "manifest.json").write_text((assets / "demo" / "manifest.json").read_text() + " ")
    with pytest.raises(ManifestError, match="descriptor"):
        cat.resolve(index, "demo", "1.0", LINUX, NONE, lambda rel: (assets / rel).read_bytes())


def test_unknown_fields_fail_at_parse(tmp_path):
    rec = pack(tree(tmp_path), "demo", "1.0", LINUX, NONE, tmp_path / "dist")
    text = cat.dumps(cat.add_platform(cat.empty_catalog("demo"), "1.0", rec.entry))
    with pytest.raises(ManifestError, match="unknown field"):
        parse_catalog(text.replace('"filename"', '"surprise": 1, "filename"', 1))


def test_floor_is_measured(tmp_path):
    exe = tmp_path / "bin" / "probe"
    exe.parent.mkdir()
    src = tmp_path / "probe.c"
    src.write_text('#include <stdio.h>\nint main(void){puts("x");return 0;}\n')
    if subprocess.run(["cc", "-o", str(exe), str(src)], check=False).returncode:
        pytest.skip("no C compiler")
    ok = measure_floor(tmp_path / "bin", "2.99")
    assert ok == []
    too_old_floor = measure_floor(tmp_path / "bin", "2.0")
    assert [v.path for v in too_old_floor] == ["probe"]


def test_a_rebuild_sits_beside_the_original_and_pins_pick_one(tmp_path):
    first = pack(tree(tmp_path, "one"), "demo", "1.0", LINUX, NONE, tmp_path / "d1")
    (tmp_path / "src").rename(tmp_path / "old")
    rebuilt = pack(tree(tmp_path, "two"), "demo", "1.0", LINUX, NONE, tmp_path / "d2", label="r2")
    assert rebuilt.entry.variant.flavor == "r2"
    assert rebuilt.entry.asset.filename == "demo-1.0-linux-x86_64-glibc2.28-r2.tar.zst"
    assets = tmp_path / "assets"
    assets.mkdir()
    catalog = cat.add_platform(cat.empty_catalog("demo"), "1.0", first.entry)
    catalog = cat.add_platform(catalog, "1.0", rebuilt.entry)
    cat.write_catalog(assets, catalog)
    index = cat.write_index(assets, Summaries(()))
    validate_document(json.loads((assets / "demo" / "manifest.json").read_text()))
    release = catalog.release("1.0")
    assert release is not None and len(release.platforms) == 2

    def fetch(rel):
        return (assets / rel).read_bytes()

    old = cat.resolve(index, "demo", "1.0", LINUX, NONE, fetch, first.entry.asset.sha256)
    new = cat.resolve(index, "demo", "1.0", LINUX, NONE, fetch, rebuilt.entry.asset.sha256)
    assert (old, new) == (first.entry.asset, rebuilt.entry.asset)
    with pytest.raises(ManifestError, match="2 candidates matched"):
        cat.resolve(index, "demo", "1.0", LINUX, NONE, fetch)


def _published(tmp_path, *platforms):
    """Pack one demo 1.0 build per platform into one catalog; returns (index, fetch, records)."""
    records = []
    for n, platform in enumerate(platforms):
        src = tree(tmp_path / f"t{n}", f"build {n}")
        records.append(pack(src, "demo", "1.0", platform, NONE, tmp_path / f"d{n}"))
    assets = tmp_path / "assets"
    assets.mkdir()
    catalog = cat.empty_catalog("demo")
    for rec in records:
        catalog = cat.add_platform(catalog, "1.0", rec.entry)
    cat.write_catalog(assets, catalog)
    index = cat.write_index(assets, Summaries(()))
    return index, (lambda rel: (assets / rel).read_bytes()), records


def test_an_arch_alias_resolves_as_in_manifest_json(tmp_path):
    index, fetch, (rec,) = _published(tmp_path, LINUX)
    got = cat.resolve(index, "demo", "1.0", Platform.from_spec("os=linux,arch=amd64"), NONE, fetch)
    assert got == rec.entry.asset


def test_an_entry_without_a_field_matches_a_query_with_it(tmp_path):
    index, fetch, (rec,) = _published(tmp_path, Platform.from_spec("os=linux,arch=x86_64"))
    got = cat.resolve(index, "demo", "1.0", LINUX, NONE, fetch)
    assert got == rec.entry.asset


def test_the_most_specific_entry_wins(tmp_path):
    generic = Platform.from_spec("os=linux,arch=x86_64")
    index, fetch, (_, explicit) = _published(tmp_path, generic, LINUX)
    got = cat.resolve(index, "demo", "1.0", LINUX, NONE, fetch)
    assert got == explicit.entry.asset


def test_a_universal2_mac_build_serves_arm64(tmp_path):
    index, fetch, (rec,) = _published(tmp_path, Platform.from_spec("os=darwin,arch=universal2,os_version=11.0"))
    got = cat.resolve(index, "demo", "1.0", Platform.from_spec("os=darwin,arch=arm64"), NONE, fetch)
    assert got == rec.entry.asset
