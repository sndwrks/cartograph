"""The export manifest: what we wrote, and what it hashed to.

Without it the exporter cannot tell "a file I wrote and nobody touched" from
"a file a human wrote", and the difference decides whether overwriting is
routine or destructive.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

MANIFEST_NAME = ".cartograph-manifest.json"
VERSION = 1


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_manifest(out: Path) -> dict:
    path = out / MANIFEST_NAME
    if not path.is_file():
        return {"version": VERSION, "repository": None, "files": {}}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        # a corrupt manifest must not be load-bearing: fall back to "we have
        # written nothing", which makes every existing file a conflict rather
        # than silently overwriting one
        return {"version": VERSION, "repository": None, "files": {}}
    data.setdefault("files", {})
    return data


def write_manifest(out: Path, repository: str, files: dict[str, dict]) -> None:
    path = out / MANIFEST_NAME
    payload = {"version": VERSION, "repository": repository, "files": files}
    # sort_keys so the manifest itself is byte-stable across runs
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def recorded_hash(manifest: dict, path: PurePosixPath) -> str | None:
    entry = manifest["files"].get(str(path))
    return entry.get("sha256") if entry else None
