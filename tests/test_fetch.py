"""fetch: retries with backoff, one root manifest per run, concurrent installs (#3)."""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import pytest

from obs_studio_libs import catalog as cat
from obs_studio_libs import fetch
from obs_studio_libs.model import ManifestError, Platform, Summaries, Variant
from obs_studio_libs.pack import pack

LINUX = Platform.from_spec("os=linux,arch=x86_64,libc=glibc,os_version=2.28")
NONE = Variant()
BASE = "https://raw.githubusercontent.com/obs-rust/obs-studio-libs/assets/"
ROOT = BASE + "manifest.json"
TOOLS = ("alpha", "beta", "gamma")


class FakeOpener:
    """Serves the assets dir under BASE and the packed archives by basename."""

    def __init__(self, assets: Path, dist: Path, fail_first: int = 0, delay: float = 0.0):
        self.assets, self.dist, self.fail_first, self.delay = assets, dist, fail_first, delay
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def open(self, url, timeout=None):
        with self.lock:
            self.calls.append(url)
            n = self.calls.count(url)
        if n <= self.fail_first:
            raise OSError(f"transient failure {n} for {url}")
        if url.startswith(BASE):
            data = (self.assets / url[len(BASE) :]).read_bytes()
        else:
            if self.delay:
                time.sleep(self.delay)
            data = (self.dist / url.rsplit("/", 1)[1]).read_bytes()
        return io.BytesIO(data)


def published(tmp: Path):
    assets, dist = tmp / "assets", tmp / "dist"
    assets.mkdir()
    pins = []
    for tool in TOOLS:
        src = tmp / f"src-{tool}"
        (src / "lib").mkdir(parents=True)
        (src / "lib" / f"{tool}.txt").write_text(tool)
        rec = pack(src, tool, "1.0", LINUX, NONE, dist)
        cat.write_catalog(assets, cat.add_platform(cat.load_catalog(assets, tool), rec.version, rec.entry))
        pins.append(fetch.Pin(tool, "1.0", LINUX, NONE, rec.entry.asset.sha256))
    cat.write_index(assets, Summaries(tuple((t, t) for t in TOOLS)))
    return assets, dist, pins


@pytest.fixture
def no_sleep(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(fetch, "_sleep", waits.append)
    return waits


def test_a_flaky_url_is_retried_with_backoff(tmp_path, monkeypatch, no_sleep):
    assets, dist, pins = published(tmp_path)
    opener = FakeOpener(assets, dist, fail_first=2)
    monkeypatch.setattr(fetch, "_OPENER", opener)
    fetch.install(pins[0], tmp_path / "out", ROOT)
    assert (tmp_path / "out" / "lib" / "alpha.txt").read_text() == "alpha"
    assert no_sleep == [1, 4, 1, 4, 1, 4]  # root, catalog, archive: each failed twice


def test_retries_are_bounded(tmp_path, monkeypatch, no_sleep):
    assets, dist, pins = published(tmp_path)
    opener = FakeOpener(assets, dist, fail_first=99)
    monkeypatch.setattr(fetch, "_OPENER", opener)
    with pytest.raises(ManifestError):
        fetch.install(pins[0], tmp_path / "out", ROOT)
    assert opener.calls.count(ROOT) == fetch.ATTEMPTS == 3
    assert no_sleep == [1, 4]


def test_the_root_manifest_is_fetched_once_per_run(tmp_path, monkeypatch, no_sleep):
    assets, dist, pins = published(tmp_path)
    opener = FakeOpener(assets, dist)
    monkeypatch.setattr(fetch, "_OPENER", opener)
    fetch.install_all([(p, tmp_path / p.tool) for p in pins], ROOT)
    assert opener.calls.count(ROOT) == 1
    for tool in TOOLS:
        assert (tmp_path / tool / "lib" / f"{tool}.txt").read_text() == tool


def test_downloads_overlap(tmp_path, monkeypatch, no_sleep):
    assets, dist, pins = published(tmp_path)
    monkeypatch.setattr(fetch, "_OPENER", FakeOpener(assets, dist, delay=0.5))
    start = time.monotonic()
    fetch.install_all([(p, tmp_path / p.tool) for p in pins], ROOT)
    assert time.monotonic() - start < 1.0  # three 0.5 s downloads: about max, not sum (1.5 s)
