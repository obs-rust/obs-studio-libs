# obs-studio-libs

Prebuilt build dependencies for [OBS-Studio-Rust](https://github.com/obs-rust/obs-studio),
compiled once per version and per platform, then downloaded by every build
instead of being compiled again (obs-rust/obs-studio#525, #926).

## Layout

Code is on `main`. The catalogs are on the orphan **`assets`** branch, the
layout [soldr-toolchain](https://github.com/zackees/soldr-toolchain) uses:

| Path (assets branch) | What |
|---|---|
| `manifest.json` | **The root.** The [manifest.json](https://github.com/zackees/manifest.json) **Index** every consumer starts from: one entry per tool, pointing at its Catalog by relative URL, sha256 and size. |
| `<tool>/manifest.json` | The tool's **Catalog**: channels (`latest-stable`, `stable`), and per version a Release with one Asset per platform. |

| Elsewhere | What |
|---|---|
| Release `<tool>-<version>` | The assets: `<tool>-<version>-<platform>[-<variant>].tar.zst`, zstd level 9. |
| `obs_studio_libs/` (main) | The `obs-studio-libs` CLI: `pack` (directory to `.tar.zst`, measuring the glibc floor on Linux), `ingest` (a zackees/forge artifact), `add` (record into the Catalog and rewrite the root Index), `slice`, and `fetch` (resolve from the root and install). |

Root: `https://raw.githubusercontent.com/obs-rust/obs-studio-libs/assets/manifest.json`

## Plain HTTPS, no GitHub API

Consumers fetch everything as static files:

- the root and the catalogs: `https://raw.githubusercontent.com/obs-rust/obs-studio-libs/assets/manifest.json`, `.../assets/<tool>/manifest.json`
- assets: `https://github.com/obs-rust/obs-studio-libs/releases/download/<tool>-<version>/<file>`

Neither is `api.github.com`, so a build needs no token and is not
rate-limited. Every asset is pinned by sha256, and the Index pins each Catalog
by sha256, so the chain is verifiable end to end. A consumer normally commits an
EmbeddedSlice (`scripts/libs.py slice`) and needs no network lookup to know
what to download.

## Platforms

| Platform tuple | Built by |
|---|---|
| `os=linux,arch=x86_64,libc=glibc,os_version=2.28` | `recipes/qt6/linux/` (manylinux_2_28, AlmaLinux 8) via `bosn run --task qt6-linux` |
| `os=windows,arch=x86_64,libc=msvc` | `.github/workflows/qt6.yml` on `windows-2022`, with obs-deps' recipe |
| `os=windows,arch=aarch64,libc=msvc` | `.github/workflows/qt6.yml` on `windows-11-arm` |
| `os=darwin,arch=universal2,os_version=11.0` | `.github/workflows/qt6.yml` on `macos-15` |

For Linux, `os_version` is the glibc floor: the oldest glibc the libraries run on.

## Tools

- **qt6**: Qt 6. Linux has qtbase, qtsvg and qtwayland; Windows and macOS have
  obs-deps' Qt set. Each archive's contents are a Qt install prefix (`lib/`,
  `include/`, `plugins/`, `lib/cmake/Qt6*`). Qt's CMake packages are
  relocatable, so the prefix can be extracted anywhere.

## Development

```sh
uv run --group dev pytest        # model, catalog, immutability, floor, no-dict lint
uv run --group dev ruff check .
```

JSON is parsed eagerly into typed, frozen dataclasses (`obs_studio_libs/model.py`,
strict: unknown or missing fields fail with their path). Nothing else touches a
dictionary; `tests/test_no_dict_access.py` fails on string-keyed subscripts,
`.get("...")`, dict literals and `dict()` outside the model.

Published bytes are immutable, as in soldr-toolchain: `add` refuses an asset
whose filename is already catalogued with another sha256 (`--replace` is the
deliberate override), and a rebuild of a published version is packed with
`--label` and published beside the original.

The dispatch-only **Linux tools** workflow (`.github/workflows/linux.yml`) builds
FFmpeg in the same pinned manylinux 2.28 image as `bosn run --task linux`, with
`/src` and `/opt/obs-deps` mounted the same way. Select `tool=ffmpeg`, a matching
`version`, the recipe `ref` (prefer a full commit), and an optional rebuild
`label` such as `r7-ci`. It uploads the usual `.tar.zst`, its pack record and
`provenance.txt` as a workflow artifact. The archive contains the install prefix,
not an enclosing `ffmpeg/` directory. The packer enforces the glibc 2.28 floor.
This initial producer does not publish releases or update the `assets` catalog;
compare its output with the existing release before publishing or moving a
consumer. Use a fresh label for a rebuild; never replace published bytes.
