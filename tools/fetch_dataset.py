"""Download the McMaster LG 18650HG2 test data and check every file against its fingerprint.

The file list, with each file's SHA-256 as published by Mendeley Data, is data/dataset.json;
tools/make_manifest.py builds it from the Mendeley record. A file is written only if its
fingerprint matches, so the analysis always runs on exactly the published measurements.

    python tools/fetch_dataset.py            # download what is missing, verify everything
    python tools/fetch_dataset.py --verify   # only verify the files already downloaded
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "dataset.json"
RAW = ROOT / "data" / "raw"
MAX_BYTES = 20_000_000  # the largest published .mat file is under 4 MB
ALLOWED_URL = "https://data.mendeley.com/public-files/datasets/b5mj79w5w9/files/"
TIMEOUT_S = 120


class DownloadError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    if not url.startswith("https://"):
        raise DownloadError(f"refusing a non-HTTPS URL: {url}")
    # The scheme is checked above and again after redirects below.
    request = urllib.request.Request(url, headers={"User-Agent": "battery-cell-lab"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        if not response.geturl().startswith("https://"):
            raise DownloadError(f"redirected to a non-HTTPS URL: {response.geturl()}")
        data: bytes = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise DownloadError(f"{url} is larger than {MAX_BYTES} bytes")
    return data


def write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)


def local_path(entry: dict[str, str]) -> Path:
    """Where a file of the manifest goes: always a plain file name inside data/raw/<folder>."""
    for part in (entry["folder"], entry["filename"]):
        if not part or part in {".", ".."} or Path(part).name != part or "\x00" in part:
            raise DownloadError(f"not a plain name: {part!r}")
    path = RAW / entry["folder"] / entry["filename"]
    if not path.resolve().is_relative_to(RAW.resolve()):
        raise DownloadError(f"outside {RAW}: {path}")
    return path


def checked_url(url: str) -> str:
    """Only files of the dataset's own record on Mendeley Data are downloaded."""
    if not url.startswith(ALLOWED_URL):
        raise DownloadError(f"not a Mendeley Data file of this dataset: {url}")
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="do not download, only verify")
    args = parser.parse_args(argv)
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    bad = 0
    for entry in entries:
        path = local_path(entry)
        if path.exists():
            if sha256(path.read_bytes()) != entry["sha256"]:
                print(f"MISMATCH {path.relative_to(ROOT)}")
                bad += 1
            continue
        if args.verify:
            print(f"MISSING  {path.relative_to(ROOT)}")
            bad += 1
            continue
        data = download(checked_url(entry["url"]))
        if sha256(data) != entry["sha256"]:
            print(f"REJECTED {entry['filename']}: fingerprint does not match")
            bad += 1
            continue
        write_atomically(path, data)
        print(f"ok       {path.relative_to(ROOT)}")
    print(f"{len(entries) - bad} of {len(entries)} files verified")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
