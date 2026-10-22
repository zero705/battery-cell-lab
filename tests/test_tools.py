"""The download tool takes only what the manifest lists, from the dataset, into data/raw."""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.error
from email.message import Message
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


def test_a_short_failure_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def flaky(url: str) -> bytes:
        calls.append(url)
        if len(calls) < 3:
            raise urllib.error.URLError("connection reset")
        return b"data"

    waits: list[float] = []
    monkeypatch.setattr(fetch_dataset, "download", flaky)
    monkeypatch.setattr(time, "sleep", waits.append)
    assert fetch_dataset.download_with_retries("https://x", wait_s=1.0) == b"data"
    assert len(calls) == 3
    assert waits == [1.0, 2.0]


@pytest.mark.parametrize(
    ("error", "attempts"),
    [
        (404, 1),
        (403, 1),
        (429, fetch_dataset.ATTEMPTS),
        (503, fetch_dataset.ATTEMPTS),
        (fetch_dataset.DownloadError("too large"), 1),
    ],
)
def test_lasting_errors_end_the_run(
    monkeypatch: pytest.MonkeyPatch, error: int | Exception, attempts: int
) -> None:
    calls: list[str] = []

    def failing(url: str) -> bytes:
        calls.append(url)
        if isinstance(error, Exception):
            raise error
        raise urllib.error.HTTPError(url, error, "error", Message(), io.BytesIO())

    monkeypatch.setattr(fetch_dataset, "download", failing)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises((urllib.error.HTTPError, fetch_dataset.DownloadError)) as raised:
        fetch_dataset.download_with_retries("https://x")
    if isinstance(raised.value, urllib.error.HTTPError):
        raised.value.close()
    assert len(calls) == attempts


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
