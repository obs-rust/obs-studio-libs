"""Gate: an `obs-rust/cef` release tag must resolve to a commit carrying that release's manifest.

The CEF archives this repository's `recipes/cef/*` produce are consumed by
obs-rust/obs-studio by sha256 pin, so the archives themselves are verifiable;
what was not, until obs-rust/obs-studio#2674, was *what they were built from*.
Each obs-rust/cef release now ships `releases/<tag>.json` — upstream source
commit, producing recipe commit, patch commit in use, and every asset's sha256 —
and each release tag points at the commit that adds its own file.

This test is the drift gate for that contract. For every published release it
reads the tag's target commit and, over plain HTTP, the manifest stored at that
commit, then checks:

* the manifest is served at the tag's commit (a tag pointing at an unrelated
  commit has no manifest there — that is exactly the state that was live before
  #2674, and the reason the gate exists);
* the manifest describes the release it is attached to (its `tag`);
* its asset list is exactly the release's asset list, and every sha256 matches
  the digest GitHub computes for that asset;
* every sha256 is a well-formed hex digest, and `patch_commit` is recorded as a
  commit sha or an explicit ``null``.

It needs the network (the GitHub API and raw.githubusercontent.com) and skips,
rather than fails, when they are unreachable: it is a provenance gate, not a
unit test of local code.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

import pytest

from obs_studio_libs.model import (
    CefReleaseManifest,
    GithubRelease,
    parse_cef_release_manifest,
    parse_git_ref_target,
    parse_github_releases,
)

CEF_REPO = "obs-rust/cef"
API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
MANIFEST_PATH = "releases/{tag}.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HTTP_TIMEOUT_SECONDS = 30


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read()


def _optional_fetch(url: str) -> bytes | None:
    """Fetch a URL that is allowed to be absent; any other HTTP error is a real failure."""
    try:
        return _fetch(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


@pytest.fixture(scope="module")
def published_releases() -> tuple[GithubRelease, ...]:
    try:
        releases = parse_github_releases(_fetch(f"{API_ROOT}/repos/{CEF_REPO}/releases"))
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network weather
        pytest.skip(f"GitHub is unreachable, cannot check release provenance: {exc}")
    assert releases, f"{CEF_REPO} publishes no release to check"
    return releases


@pytest.fixture(scope="module")
def tag_commits(published_releases: tuple[GithubRelease, ...]) -> tuple[tuple[str, str], ...]:
    commits = []
    for release in published_releases:
        url = f"{API_ROOT}/repos/{CEF_REPO}/git/ref/tags/{release.tag_name}"
        try:
            ref = parse_git_ref_target(_fetch(url), release.tag_name)
        except urllib.error.HTTPError as exc:
            pytest.fail(f"tag {release.tag_name} cannot be resolved: HTTP {exc.code}")
        commits.append((release.tag_name, ref))
    return tuple(commits)


def commit_for(tag_commits: tuple[tuple[str, str], ...], tag: str) -> str:
    return next(commit for name, commit in tag_commits if name == tag)


def manifest_at(commit: str, tag: str) -> CefReleaseManifest | None:
    raw = _optional_fetch(f"{RAW_ROOT}/{CEF_REPO}/{commit}/{MANIFEST_PATH.format(tag=tag)}")
    return None if raw is None else parse_cef_release_manifest(raw, f"{tag}@{commit[:12]}")


def test_every_release_tag_resolves_to_a_commit_carrying_its_manifest(
    published_releases: tuple[GithubRelease, ...], tag_commits: tuple[tuple[str, str], ...]
) -> None:
    missing = []
    for release in published_releases:
        tag = release.tag_name
        commit = commit_for(tag_commits, tag)
        if manifest_at(commit, tag) is None:
            missing.append(f"{tag} -> {commit[:12]} has no {MANIFEST_PATH.format(tag=tag)}")
    assert not missing, "release tags do not carry their own provenance manifest:\n" + "\n".join(missing)


def test_manifests_describe_their_release_and_match_every_asset_digest(
    published_releases: tuple[GithubRelease, ...], tag_commits: tuple[tuple[str, str], ...]
) -> None:
    problems: list[str] = []
    for release in published_releases:
        tag = release.tag_name
        manifest = manifest_at(commit_for(tag_commits, tag), tag)
        assert manifest is not None, f"{tag}: manifest missing at the tag's commit"
        if manifest.tag != tag:
            problems.append(f"{tag}: manifest says tag {manifest.tag!r}")
        if not manifest.has_patch_commit_key:
            problems.append(f"{tag}: no patch_commit key (a commit sha or an explicit null)")

        published = {asset.name: asset.digest for asset in release.assets}
        recorded = {asset.name: asset.sha256 for asset in manifest.assets}
        if set(recorded) != set(published):
            problems.append(
                f"{tag}: asset set differs, manifest-only {sorted(set(recorded) - set(published))},"
                f" release-only {sorted(set(published) - set(recorded))}"
            )
        for name, sha256 in recorded.items():
            if not SHA256_RE.match(sha256):
                problems.append(f"{tag}/{name}: sha256 {sha256!r} is not a sha256 hex digest")
            elif published.get(name) != f"sha256:{sha256}":
                problems.append(f"{tag}/{name}: manifest {sha256} != published {published.get(name)}")
    assert not problems, "release manifests disagree with the published assets:\n" + "\n".join(problems)
