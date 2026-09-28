"""Build data/dataset.json, the list of test files this project uses, from the Mendeley record.

The record (data/mendeley_record.json) is the public Mendeley Data API response for
the dataset, saved unchanged. It lists every file with its SHA-256. The dataset keeps the tests
of each ambient temperature in one folder; the folder's temperature is read from the names of the
files in it. Only the MATLAB files are listed: the CSV files hold the same data.

    python tools/make_manifest.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "data" / "mendeley_record.json"
MANIFEST = ROOT / "data" / "dataset.json"
RECORD_URL = "https://data.mendeley.com/public-api/datasets/b5mj79w5w9"
TEMPERATURE = re.compile(r"_(n?)(\d+)degC_")


def folder_name(filenames: list[str]) -> str:
    """The ambient temperature most file names in a folder carry, e.g. "n10degC" for -10 °C.

    Charges and the CSV copies carry no temperature, and one file in the 0 °C folder is named
    10 °C, so the name is the clear majority of the names that carry one.
    """
    found = Counter(
        f"{m.group(1)}{m.group(2)}degC" for name in filenames if (m := TEMPERATURE.search(name))
    )
    (name, count), *_ = found.most_common(1)
    if count < 0.9 * found.total():
        raise ValueError(f"no clear temperature in the folder of {filenames[0]}: {found}")
    return name


def main() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    folders: dict[str, list[str]] = {}
    for f in record["files"]:
        if f.get("folder_id"):
            folders.setdefault(f["folder_id"], []).append(f["filename"])
    names = {fid: folder_name(files) for fid, files in folders.items()}
    if len(set(names.values())) != len(names):
        raise ValueError(f"two folders map to the same temperature: {names}")
    files = [
        {
            "folder": names[f["folder_id"]],
            "filename": f["filename"],
            "size": f["size"],
            "sha256": f["content_details"]["sha256_hash"],
            "url": f["content_details"]["download_url"],
        }
        for f in record["files"]
        if f.get("folder_id") and f["filename"].endswith(".mat")
    ]
    files.sort(key=lambda e: (e["folder"], e["filename"]))
    licence = record["data_licence"]
    manifest = {
        "dataset": record["name"],
        "doi": f"https://doi.org/{record['doi']['id']}",
        "version": record["version"],
        "published": record["versions"][0]["publish_date"][:10],
        "authors": [
            f"{c['first_name'].strip()} {c['last_name'].strip()}" for c in record["contributors"]
        ],
        "institution": "McMaster University",
        "licence": {"name": licence["full_name"], "url": licence["url"]},
        "record": RECORD_URL,
        "files": files,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(files)} files in {len(names)} folders: {sorted(set(names.values()))}")


if __name__ == "__main__":
    main()
