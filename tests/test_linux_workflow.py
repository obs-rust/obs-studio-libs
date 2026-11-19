"""The dispatch producer must reject mismatched recipes before starting Docker."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "recipes/linux/ci-build.sh"


@pytest.mark.parametrize(
    ("tool", "version", "label", "ok"),
    [
        ("ffmpeg", "8.1.3", "r7-ci", True),
        ("ffmpeg", "8.1.3", "", True),
        ("ffmpeg", "8.1.2", "r7-ci", False),
        ("../ffmpeg", "8.1.3", "r7-ci", False),
        ("curl", "8.1.3", "r7-ci", False),
        ("ffmpeg", "8.1.3", "../bad", False),
        ("qt6", "6.11.1", "testlib", True),
        ("qt6", "6.11.0", "testlib", False),
    ],
)
def test_dispatch_validation(tool, version, label, ok):
    result = subprocess.run(
        ["bash", str(SCRIPT), "check", tool, version, label],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is ok, result.stderr


def test_dispatch_is_artifact_only():
    workflow = (ROOT / ".github/workflows/linux.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "gh release" not in workflow
    assert "actions/upload-artifact@" in workflow


def test_qt6_workflow_builds_and_publishes_linux():
    """The Linux Qt asset is built and published by qt6.yml like the Windows
    and macOS ones, not by hand (obs-rust/obs-studio#4837)."""
    workflow = (ROOT / ".github/workflows/qt6.yml").read_text()
    assert "bash recipes/linux/ci-build.sh build qt6" in workflow
    assert "needs: [build, build-linux]" in workflow
    # A rebuild of one platform gets a label; published bytes stay immutable.
    assert "label:" in workflow
    assert "platforms:" in workflow
    assert "--clobber" not in workflow.replace("Never --clobber", "")
