"""Consumer side: resolve from the root manifest.json and install an asset.

Plain HTTPS from raw.githubusercontent.com and github.com release downloads
(and the CDN hosts those redirect to). The GitHub API is never used; any other
host is refused, redirects included.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .catalog import ASSETS_RAW, resolve
from .model import Asset, Index, ManifestError, Platform, Variant, parse_index

ROOT_URL = f"{ASSETS_RAW}/manifest.json"
ALLOWED_HOSTS = frozenset(
    {"raw.githubusercontent.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)


def check_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise ManifestError(f"refusing {url}: only https from {sorted(ALLOWED_HOSTS)} (never the GitHub API)")
    return url


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirects)


ATTEMPTS = 3
BACKOFF = (1, 4)  # seconds before attempt 2 and 3
WORKERS = 4
_sleep = time.sleep


def _retry(url: str, fn):
    """fn(response) for url, retried with exponential backoff on OSError."""
    for attempt in range(ATTEMPTS):
        try:
            with _OPENER.open(check_url(url), timeout=60) as r:
                return fn(r)
        except OSError:
            if attempt + 1 == ATTEMPTS:
                raise
            _sleep(BACKOFF[attempt])


def get(url: str) -> bytes:
    try:
        return _retry(url, lambda r: r.read())
    except OSError as e:
        raise ManifestError(f"could not download {url}: {e}") from e


@dataclass(frozen=True)
class Pin:
    """What a consumer pins: the tool version for its platform, and the bytes it expects."""

    tool: str
    version: str
    platform: Platform
    variant: Variant
    sha256: str


def install(pin: Pin, dest: Path, root_url: str = ROOT_URL, index: Index | None = None) -> Asset:
    """Install one pinned asset; pass index to reuse a root manifest already parsed."""
    if index is None:
        index = parse_index(get(root_url), root_url)
    asset = resolve(
        index,
        pin.tool,
        pin.version,
        pin.platform,
        pin.variant,
        lambda rel: get(urllib.parse.urljoin(root_url, rel)),
        pin.sha256,
    )
    if asset.sha256 != pin.sha256:
        raise ManifestError(f"{pin.tool} {pin.version}: the catalog's asset is {asset.sha256}, pinned {pin.sha256}")
    with tempfile.TemporaryDirectory(prefix="obs-studio-libs-") as tmp:
        archive = Path(tmp) / asset.filename
        errors = []
        for url in asset.urls:
            try:
                with archive.open("wb") as f:
                    _retry(url, lambda r, f=f: (f.seek(0), f.truncate(), shutil.copyfileobj(r, f, 1 << 20)))
                break
            except OSError as e:
                errors.append(f"{url}: {e}")
        else:
            raise ManifestError("could not download:\n  " + "\n  ".join(errors))
        h = hashlib.sha256()
        with archive.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if archive.stat().st_size != asset.size_bytes or h.hexdigest() != asset.sha256:
            raise ManifestError(f"{asset.filename}: size or sha256 differs from the catalog")
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:zst") as tar:
            tar.extractall(dest, filter="tar")
    return asset


def install_all(jobs: list[tuple[Pin, Path]], root_url: str = ROOT_URL, workers: int = WORKERS) -> list[Asset]:
    """Fetch the root manifest once, then download, verify and extract each pin in a bounded pool.

    Destinations must be disjoint. Returns the assets in the order of jobs."""
    index = parse_index(get(root_url), root_url)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(jobs)))) as pool:
        futures = [pool.submit(install, pin, dest, root_url, index) for pin, dest in jobs]
        return [f.result() for f in futures]
