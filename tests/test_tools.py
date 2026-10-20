"""The download tool takes only what the manifest lists, from the dataset, into data/raw."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from celllab.measurements import Measurement

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import audit_dataset  # noqa: E402
import fetch_dataset  # noqa: E402


def test_every_manifest_entry_is_a_plain_file_from_the_dataset() -> None:
    entries = json.loads((ROOT / "data" / "dataset.json").read_text(encoding="utf-8"))["files"]
    for entry in entries:
        path = fetch_dataset.local_path(entry)
        assert path.parent.parent == fetch_dataset.RAW
        assert fetch_dataset.checked_url(entry["url"]) == entry["url"]


@pytest.mark.parametrize(
    ("folder", "filename"),
    [
        ("25degC", "../../evil.mat"),
        ("..", "x.mat"),
        ("25degC", ".."),
        ("25degC", "a/b.mat"),
        ("25degC", ""),
        ("25degC", "x\x00.mat"),
    ],
)
def test_names_that_leave_the_raw_folder_are_refused(folder: str, filename: str) -> None:
    with pytest.raises(fetch_dataset.DownloadError):
        fetch_dataset.local_path({"folder": folder, "filename": filename})


@pytest.mark.parametrize(
    "url",
    [
        "http://data.mendeley.com/public-files/datasets/b5mj79w5w9/files/x",
        "https://example.org/public-files/datasets/b5mj79w5w9/files/x",
        "https://data.mendeley.com.example.org/public-files/datasets/b5mj79w5w9/files/x",
        "https://data.mendeley.com/public-files/datasets/other/files/x",
    ],
)
def test_other_addresses_are_refused(url: str) -> None:
    with pytest.raises(fetch_dataset.DownloadError, match="not a Mendeley Data file"):
        fetch_dataset.checked_url(url)


def test_download_refuses_plain_http() -> None:
    with pytest.raises(fetch_dataset.DownloadError, match="non-HTTPS"):
        fetch_dataset.download("http://data.mendeley.com/x")


def test_the_audit_finds_gaps_only_while_the_current_flows() -> None:
    t = np.array([0.0, 0.1, 0.2, 100.0, 100.1, 200.0, 200.1])
    current = np.array([-1.0, -1.0, -1.0, -1.0, 0.0, 0.0, 0.0])
    m = Measurement("m", t, np.ones(7), current, np.ones(7))
    assert audit_dataset.logging_gaps(m) == [2]  # the second long interval is a rest


def test_write_is_atomic_and_verification_catches_a_changed_file(tmp_path: Path) -> None:
    target = tmp_path / "a" / "file.mat"
    fetch_dataset.write_atomically(target, b"data")
    assert target.read_bytes() == b"data"
    assert not target.with_name("file.mat.part").exists()
    assert fetch_dataset.sha256(b"data") != fetch_dataset.sha256(b"date")
