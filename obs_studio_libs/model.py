"""The zackees/manifest.json documents obs-studio-libs reads and writes, as typed values.

This module is the only place JSON objects are touched. `parse_*` turns a
document into frozen dataclasses eagerly and strictly: every field is checked
for its type, a required field that is missing or a field the schema does not
have is an error naming its path, and nothing downstream sees a dict.
`to_json()` turns the values back into the document. tests/test_no_dict_access.py
fails on dictionary subscripts and `.get()` anywhere else.

Field names and meanings are manifest.proto's (Platform, Variant, Descriptor,
Asset, Index/ToolEntry, Catalog/Release/ReleasePlatform, EmbeddedSlice,
CompiledFor), limited to the fields obs-studio-libs uses.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from manifest_json import ResolveError, resolve_in_catalog

SCHEMA = "https://zackees.github.io/manifest.json/v1/manifest.schema.json"
MANIFEST_MEDIA_TYPE = "application/vnd.manifest.v1+json"


class ManifestError(ValueError):
    """A document that is not what the schema says, with the path of the problem."""


# --- strict reading -----------------------------------------------------------


class _Obj:
    """One JSON object being read: hands out typed fields, then insists every key was used."""

    def __init__(self, value: object, path: str) -> None:
        if not isinstance(value, Mapping):
            raise ManifestError(f"{path}: expected an object, got {type(value).__name__}")
        self._value: Mapping[str, Any] = value
        self._path = path
        self._used: set[str] = set()

    def _take(self, key: str, required: bool) -> object:
        self._used.add(key)
        if key not in self._value:
            if required:
                raise ManifestError(f"{self._path}.{key}: missing")
            return None
        return self._value[key]

    def str(self, key: str, required: bool = True, default: str = "") -> str:
        v = self._take(key, required)
        if v is None:
            return default
        if not isinstance(v, str):
            raise ManifestError(f"{self._path}.{key}: expected a string")
        return v

    def int(self, key: str, required: bool = True, default: int = 0) -> int:
        v = self._take(key, required)
        if v is None:
            return default
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ManifestError(f"{self._path}.{key}: expected a non-negative integer")
        return v

    def strs(self, key: str, required: bool = True) -> tuple[str, ...]:
        v = self._take(key, required)
        if v is None:
            return ()
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ManifestError(f"{self._path}.{key}: expected a list of strings")
        return tuple(v)

    def obj(self, key: str, required: bool = True) -> _Obj:
        v = self._take(key, required)
        return _Obj({} if v is None else v, f"{self._path}.{key}")

    def objs(self, key: str, required: bool = True) -> list[_Obj]:
        v = self._take(key, required)
        if v is None:
            return []
        if not isinstance(v, list):
            raise ManifestError(f"{self._path}.{key}: expected a list")
        return [_Obj(x, f"{self._path}.{key}[{i}]") for i, x in enumerate(v)]

    def obj_map(self, key: str, required: bool = True) -> list[tuple[str, _Obj]]:
        sub = self.obj(key, required)
        sub._used = set(sub._value)
        return [(k, _Obj(v, f"{sub._path}.{k}")) for k, v in sub._value.items()]

    def str_map(self, key: str, required: bool = True) -> tuple[tuple[str, str], ...]:
        sub = self.obj(key, required)
        return tuple((k, sub.str(k)) for k in list(sub._value))

    def done(self) -> None:
        extra = sorted(set(self._value) - self._used)
        if extra:
            raise ManifestError(f"{self._path}: unknown field(s) {', '.join(extra)}")


def _kind(o: _Obj, expected: str) -> None:
    got = o.str("kind")
    if got != expected:
        raise ManifestError(f"{o._path}.kind: expected {expected!r}, got {got!r}")
    if o.int("schema_version") != 1:
        raise ManifestError(f"{o._path}.schema_version: only 1 is supported")
    o.str("$schema", required=False)


def _drop_empty(d: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in d.items() if v not in ("", (), [], {}, None)}


# --- values ---------------------------------------------------------------------


@dataclass(frozen=True)
class Platform:
    os: str
    arch: str
    os_version: str = ""
    libc: str = ""
    abi: str = ""

    FIELDS = ("os", "arch", "os_version", "libc", "abi")

    @staticmethod
    def parse(o: _Obj) -> Platform:
        p = Platform(o.str("os"), o.str("arch"), o.str("os_version", False), o.str("libc", False), o.str("abi", False))
        o.done()
        return p

    @staticmethod
    def from_spec(spec: str) -> Platform:
        """os=linux,arch=x86_64,libc=glibc,os_version=2.28"""
        values = _parse_spec(spec, Platform.FIELDS)
        if "os" not in values or "arch" not in values:
            raise ManifestError(f"platform {spec!r}: os and arch are required")
        return Platform(**values)

    def matches(self, want: Platform) -> bool:
        """A field the query leaves empty is a wildcard (the manifest.json resolution rule)."""
        return all(not w or w == mine for w, mine in zip(_fields(want), _fields(self), strict=True))

    def flat(self) -> str:
        """linux-x86_64-glibc2.28, darwin-universal2-11.0, windows-x86_64"""
        parts = [self.os, self.arch]
        if self.libc and self.libc != "msvc":
            parts.append(self.libc + self.os_version)
        elif self.os_version:
            parts.append(self.os_version)
        return "-".join(parts)

    def to_json(self) -> dict[str, object]:
        return _drop_empty(
            {"os": self.os, "arch": self.arch, "os_version": self.os_version, "libc": self.libc, "abi": self.abi}
        )


@dataclass(frozen=True)
class Variant:
    optimization: str = ""
    edition: str = ""
    flavor: str = ""

    FIELDS = ("optimization", "edition", "flavor")

    @staticmethod
    def parse(o: _Obj) -> Variant:
        v = Variant(o.str("optimization", False), o.str("edition", False), o.str("flavor", False))
        o.done()
        return v

    @staticmethod
    def from_spec(spec: str) -> Variant:
        return Variant(**_parse_spec(spec, Variant.FIELDS))

    def matches(self, want: Variant) -> bool:
        return all(not w or w == mine for w, mine in zip(_fields(want), _fields(self), strict=True))

    def flat(self) -> str:
        return "-".join(x for x in (self.optimization, self.edition, self.flavor) if x)

    def to_json(self) -> dict[str, object]:
        return _drop_empty({"optimization": self.optimization, "edition": self.edition, "flavor": self.flavor})


def _fields(v: Platform | Variant) -> tuple[str, ...]:
    return tuple(getattr(v, f) for f in v.FIELDS)


def _parse_spec(spec: str, allowed: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in filter(None, spec.split(",")):
        key, _, value = part.partition("=")
        if key not in allowed or not value:
            raise ManifestError(f"{part!r}: expected key=value with key in {allowed}")
        out[key] = value
    return out


@dataclass(frozen=True)
class Descriptor:
    url: str
    sha256: str
    size_bytes: int
    media_type: str = ""

    @staticmethod
    def parse(o: _Obj) -> Descriptor:
        d = Descriptor(o.str("url"), o.str("sha256"), o.int("size_bytes"), o.str("media_type", False))
        o.done()
        return d

    def to_json(self) -> dict[str, object]:
        return _drop_empty(
            {"url": self.url, "sha256": self.sha256, "size_bytes": self.size_bytes, "media_type": self.media_type}
        )


@dataclass(frozen=True)
class Asset:
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    urls: tuple[str, ...]

    @staticmethod
    def parse(o: _Obj) -> Asset:
        a = Asset(o.str("filename"), o.str("media_type"), o.int("size_bytes"), o.str("sha256"), o.strs("urls"))
        o.done()
        if not a.urls:
            raise ManifestError(f"{o._path}.urls: empty")
        return a

    def to_json(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "urls": list(self.urls),
        }


@dataclass(frozen=True)
class ReleasePlatform:
    platform: Platform
    variant: Variant
    asset: Asset

    @staticmethod
    def parse(o: _Obj) -> ReleasePlatform:
        rp = ReleasePlatform(
            Platform.parse(o.obj("platform")), Variant.parse(o.obj("variant", False)), Asset.parse(o.obj("asset"))
        )
        o.done()
        return rp

    def to_json(self) -> dict[str, object]:
        return {"platform": self.platform.to_json(), "variant": self.variant.to_json(), "asset": self.asset.to_json()}


@dataclass(frozen=True)
class Release:
    version: str
    published_at: str
    platforms: tuple[ReleasePlatform, ...]

    @staticmethod
    def parse(o: _Obj) -> Release:
        r = Release(
            o.str("version"), o.str("published_at", False), tuple(ReleasePlatform.parse(p) for p in o.objs("platforms"))
        )
        o.done()
        return r

    def to_json(self) -> dict[str, object]:
        return _drop_empty(
            {
                "version": self.version,
                "published_at": self.published_at,
                "platforms": [p.to_json() for p in self.platforms],
            }
        )


@dataclass(frozen=True)
class Catalog:
    tool: str
    online_url: str
    channels: tuple[tuple[str, str], ...]
    releases: tuple[Release, ...]

    @staticmethod
    def parse(o: _Obj) -> Catalog:
        _kind(o, "Catalog")
        c = Catalog(
            o.str("tool"),
            o.str("online_url", False),
            o.str_map("channels", False),
            tuple(Release.parse(r) for r in o.objs("releases")),
        )
        o.done()
        return c

    def channel(self, name: str) -> str | None:
        return next((v for k, v in self.channels if k == name), None)

    def release(self, version_or_channel: str) -> Release | None:
        version = self.channel(version_or_channel) or version_or_channel
        return next((r for r in self.releases if r.version == version), None)

    def to_json(self) -> dict[str, object]:
        return {
            "$schema": SCHEMA,
            "kind": "Catalog",
            "schema_version": 1,
            "tool": self.tool,
            "online_url": self.online_url,
            "channels": dict(self.channels),
            "releases": [r.to_json() for r in self.releases],
        }


@dataclass(frozen=True)
class ToolEntry:
    descriptor: Descriptor
    summary: str = ""
    kind_hint: str = ""

    @staticmethod
    def parse(o: _Obj) -> ToolEntry:
        t = ToolEntry(Descriptor.parse(o.obj("descriptor")), o.str("summary", False), o.str("kind_hint", False))
        o.done()
        return t

    def to_json(self) -> dict[str, object]:
        return _drop_empty(
            {"descriptor": self.descriptor.to_json(), "summary": self.summary, "kind_hint": self.kind_hint}
        )


@dataclass(frozen=True)
class Index:
    tools: tuple[tuple[str, ToolEntry], ...] = field(default=())

    @staticmethod
    def parse(o: _Obj) -> Index:
        _kind(o, "Index")
        i = Index(tuple((name, ToolEntry.parse(t)) for name, t in o.obj_map("tools", False)))
        o.done()
        return i

    def tool(self, name: str) -> ToolEntry | None:
        return next((t for n, t in self.tools if n == name), None)

    def to_json(self) -> dict[str, object]:
        return {
            "$schema": SCHEMA,
            "kind": "Index",
            "schema_version": 1,
            "tools": {n: t.to_json() for n, t in sorted(self.tools)},
        }


@dataclass(frozen=True)
class EmbeddedSlice:
    tool: str
    platform: Platform
    variant: Variant
    channel: str
    compiled_version: str
    asset: Asset
    online_url: str = ""
    online_sha256: str = ""

    @staticmethod
    def parse(o: _Obj) -> EmbeddedSlice:
        _kind(o, "EmbeddedSlice")
        cf = o.obj("compiled_for")
        platform = Platform.parse(cf.obj("platform"))
        variant = Variant.parse(cf.obj("variant", False))
        channel = cf.str("channel")
        cf.done()
        s = EmbeddedSlice(
            o.str("tool"),
            platform,
            variant,
            channel,
            o.str("compiled_version"),
            Asset.parse(o.obj("asset")),
            o.str("online_url", False),
            o.str("online_sha256", False),
        )
        o.done()
        return s

    def to_json(self) -> dict[str, object]:
        return _drop_empty(
            {
                "$schema": SCHEMA,
                "kind": "EmbeddedSlice",
                "schema_version": 1,
                "tool": self.tool,
                "compiled_for": {
                    "platform": self.platform.to_json(),
                    "variant": self.variant.to_json(),
                    "channel": self.channel,
                },
                "compiled_version": self.compiled_version,
                "asset": self.asset.to_json(),
                "online_url": self.online_url,
                "online_sha256": self.online_sha256,
            }
        )


@dataclass(frozen=True)
class Summaries:
    """summaries.json (main branch): tool -> the one-line summary its Index entry carries."""

    entries: tuple[tuple[str, str], ...]

    @staticmethod
    def parse(o: _Obj) -> Summaries:
        s = Summaries(tuple((k, o.str(k)) for k in sorted(o._value)))
        o.done()
        return s

    def of(self, tool: str) -> str:
        return next((v for k, v in self.entries if k == tool), "")


@dataclass(frozen=True)
class PackRecord:
    """What `pack`/`ingest` write next to an archive and `add` records: one ReleasePlatform of a tool version."""

    tool: str
    version: str
    entry: ReleasePlatform

    @staticmethod
    def parse(o: _Obj) -> PackRecord:
        r = PackRecord(o.str("tool"), o.str("version"), ReleasePlatform.parse(o.obj("entry")))
        o.done()
        return r

    def to_json(self) -> dict[str, object]:
        return {"tool": self.tool, "version": self.version, "entry": self.entry.to_json()}


@dataclass(frozen=True)
class LockedTool:
    """One dependency a consumer pins: which build, for which platform, with which bytes, installed where."""

    tool: str
    version: str
    platform: Platform
    variant: Variant
    sha256: str
    install: str

    @staticmethod
    def parse(o: _Obj) -> LockedTool:
        t = LockedTool(
            o.str("tool"),
            o.str("version"),
            Platform.parse(o.obj("platform")),
            Variant.parse(o.obj("variant", False)),
            o.str("sha256"),
            o.str("install"),
        )
        o.done()
        return t


@dataclass(frozen=True)
class Lock:
    """A consumer's lock file (e.g. obs-studio's deps.lock.json): the root to resolve from and its pins."""

    root: str
    tools: tuple[LockedTool, ...]

    @staticmethod
    def parse(o: _Obj) -> Lock:
        lock = Lock(o.str("root"), tuple(LockedTool.parse(t) for t in o.objs("tools")))
        o.done()
        return lock


# --- documents --------------------------------------------------------------------


def _load(text: str | bytes, where: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ManifestError(f"{where}: not JSON ({e})") from None


def parse_index(text: str | bytes, where: str = "manifest.json") -> Index:
    return Index.parse(_Obj(_load(text, where), where))


def parse_catalog(text: str | bytes, where: str = "catalog") -> Catalog:
    return Catalog.parse(_Obj(_load(text, where), where))


def parse_slice(text: str | bytes, where: str = "slice") -> EmbeddedSlice:
    return EmbeddedSlice.parse(_Obj(_load(text, where), where))


def parse_summaries(text: str | bytes, where: str = "summaries.json") -> Summaries:
    return Summaries.parse(_Obj(_load(text, where), where))


def parse_lock(text: str | bytes, where: str = "deps.lock.json") -> Lock:
    return Lock.parse(_Obj(_load(text, where), where))


def parse_record(text: str | bytes, where: str = "record") -> PackRecord:
    return PackRecord.parse(_Obj(_load(text, where), where))


def dumps(value: Index | Catalog | EmbeddedSlice | ReleasePlatform | PackRecord) -> str:
    return json.dumps(value.to_json(), indent=2) + "\n"


def pick_platform(tool: str, release: Release, platform: Platform, variant: Variant) -> ReleasePlatform:
    """The one entry of release for platform and variant, by manifest.json's own resolver
    (arch aliases, wildcards, specificity, ambiguity), as soldr-toolchain resolves."""
    doc = Catalog(tool, "", (("pinned", release.version),), (release,)).to_json()
    try:
        got = resolve_in_catalog(doc, tool, platform.to_json(), "pinned", variant.to_json())
    except ResolveError as e:
        raise ManifestError(f"{tool} {release.version}: {platform} {variant}: {e}") from e
    return next(p for p in release.platforms if p.asset.to_json() == got)
