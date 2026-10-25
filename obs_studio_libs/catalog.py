"""Catalog and Index operations, on the typed model only (no dictionaries)."""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import replace
from pathlib import Path

from .model import (
    MANIFEST_MEDIA_TYPE,
    Asset,
    Catalog,
    Descriptor,
    EmbeddedSlice,
    Index,
    ManifestError,
    Platform,
    Release,
    ReleasePlatform,
    Summaries,
    ToolEntry,
    Variant,
    dumps,
    parse_catalog,
    parse_index,
    pick_platform,
)

REPO = "obs-rust/obs-studio-libs"
ASSETS_RAW = f"https://raw.githubusercontent.com/{REPO}/assets"  # the orphan assets branch


def release_tag(tool: str, version: str) -> str:
    return f"{tool}-{version}"


def asset_url(tool: str, version: str, filename: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{release_tag(tool, version)}/{filename}"


def _version_key(version: str) -> tuple[tuple[int, str], ...]:
    return tuple((int(p), "") if p.isdigit() else (-1, p) for p in version.replace("-", ".").split("."))


def add_platform(catalog: Catalog, version: str, entry: ReleasePlatform, replace_bytes: bool = False) -> Catalog:
    """The catalog with entry recorded under version.

    Published bytes are immutable (as in soldr-toolchain): an entry for the
    same platform and variant whose filename is already catalogued with a
    different sha256 is refused unless replace_bytes, because consumers pin
    (filename, sha256). Republish a rebuild under a build label instead.
    """
    for release in catalog.releases:
        for existing in release.platforms:
            if (
                existing.asset.filename == entry.asset.filename
                and existing.asset.sha256 != entry.asset.sha256
                and not replace_bytes
            ):
                raise ManifestError(
                    f"{entry.asset.filename} is already published with sha256 {existing.asset.sha256}; "
                    "published bytes are immutable: rebuild under a build label, or pass --replace"
                )
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    current = catalog.release(version)
    kept = tuple(
        p for p in (current.platforms if current else ()) if (p.platform, p.variant) != (entry.platform, entry.variant)
    )
    platforms = tuple(sorted((*kept, entry), key=lambda p: (p.platform.flat(), p.variant.flat())))
    updated = Release(version, now, platforms)
    releases = (*tuple(r for r in catalog.releases if r.version != version), updated)
    releases = tuple(sorted(releases, key=lambda r: _version_key(r.version), reverse=True))
    newest = releases[0].version
    others = tuple((k, v) for k, v in catalog.channels if k not in ("latest-stable", "stable"))
    stable = catalog.channel("stable") or newest
    channels = tuple(sorted((*others, ("latest-stable", newest), ("stable", stable))))
    return replace(catalog, channels=channels, releases=releases)


def empty_catalog(tool: str) -> Catalog:
    return Catalog(tool, f"{ASSETS_RAW}/{tool}/manifest.json", (), ())


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_index(assets: Path, summaries: Summaries) -> Index:
    """The root manifest.json: one ToolEntry per <tool>/manifest.json, by relative URL."""
    tools = []
    for path in sorted(assets.glob("*/manifest.json")):
        raw = path.read_bytes()
        parse_catalog(raw, str(path))  # only valid catalogs are indexed
        tool = path.parent.name
        tools.append(
            (
                tool,
                ToolEntry(
                    Descriptor(f"{tool}/manifest.json", sha256_bytes(raw), len(raw), MANIFEST_MEDIA_TYPE),
                    summaries.of(tool),
                    "library",
                ),
            )
        )
    return Index(tuple(tools))


def load_catalog(assets: Path, tool: str) -> Catalog:
    path = assets / tool / "manifest.json"
    return parse_catalog(path.read_bytes(), str(path)) if path.exists() else empty_catalog(tool)


def write_catalog(assets: Path, catalog: Catalog) -> None:
    path = assets / catalog.tool / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(catalog))


def write_index(assets: Path, summaries: Summaries) -> Index:
    index = build_index(assets, summaries)
    (assets / "manifest.json").write_text(dumps(index))
    parse_index((assets / "manifest.json").read_bytes())
    return index


def make_slice(assets: Path, tool: str, version: str, platform: Platform, variant: Variant) -> EmbeddedSlice:
    path = assets / tool / "manifest.json"
    raw = path.read_bytes()
    catalog = parse_catalog(raw, str(path))
    release = catalog.release(version)
    if release is None:
        raise ManifestError(f"{tool} {version}: no such release")
    hits = [p for p in release.platforms if p.platform.matches(platform) and p.variant.matches(variant)]
    if len(hits) != 1:
        raise ManifestError(f"{tool} {release.version}: {len(hits)} entries match {platform} {variant}")
    hit = hits[0]
    return EmbeddedSlice(
        tool,
        hit.platform,
        hit.variant,
        release.version,
        release.version,
        hit.asset,
        catalog.online_url,
        sha256_bytes(raw),
    )


def resolve(
    index: Index, tool: str, version: str, platform: Platform, variant: Variant, fetch_catalog, sha256: str = ""
) -> Asset:
    """Index -> the tool's Catalog (checked against its descriptor) -> one Asset.

    fetch_catalog(relative_url) -> bytes is supplied by the caller (network or files)."""
    entry = index.tool(tool)
    if entry is None:
        raise ManifestError(f"{tool}: not in the Index")
    raw = fetch_catalog(entry.descriptor.url)
    if len(raw) != entry.descriptor.size_bytes or sha256_bytes(raw) != entry.descriptor.sha256:
        raise ManifestError(f"{entry.descriptor.url}: does not match the Index's descriptor")
    catalog = parse_catalog(raw, entry.descriptor.url)
    if catalog.tool != tool:
        raise ManifestError(f"{entry.descriptor.url}: is the catalog of {catalog.tool}, not {tool}")
    release = catalog.release(version)
    if release is None:
        raise ManifestError(f"{tool} {version}: no such release")
    # Several builds of a version can share a platform (a rebuild under a build label
    # beside the original): the pinned bytes decide, before manifest.json's resolver.
    if sha256:
        release = Release(
            release.version, release.published_at, tuple(p for p in release.platforms if p.asset.sha256 == sha256)
        )
    return pick_platform(tool, release, platform, variant).asset
