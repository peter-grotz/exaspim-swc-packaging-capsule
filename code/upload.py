"""Upload packaged cells to S3, one folder per cell, without overwriting or deleting.

Each file is checked before anything is written:

* absent: uploaded with ``IfNoneMatch="*"``, so S3 itself refuses the write if the key
  appears in the meantime, and with its SHA-256, which S3 verifies on receipt;
* present with the same SHA-256: skipped, so a rerun after a partial upload is safe;
* present with other content, or with no checksum to compare: a conflict, and nothing in
  that cell is written.

A cell's metadata goes up last, so a folder without ``data_description.json`` is visibly
incomplete. Nothing here deletes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

UPLOAD, DRY_RUN = "upload", "dry_run"
MODES = (DRY_RUN, UPLOAD)

UPLOADED = "uploaded"
WOULD_UPLOAD = "would_upload"
SKIPPED = "skipped_identical"
CONFLICT = "conflict"
ERROR = "error"

LAST = ("processing.json", "data_description.json")
"""Written after everything else, in this order."""

MAX_PUT_BYTES = 5 * 1024**3
"""S3's limit for a single PUT; larger files would need a multipart upload."""


@dataclass(frozen=True)
class Entry:
    """One file's outcome, as recorded in the manifest."""

    key: str
    size: int
    sha256: str
    status: str
    detail: str = ""


def parse_destination(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/prefix/`` into the bucket and a prefix ending in ``/``."""
    parsed = urlparse(uri.strip())
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Destination must be an s3:// URI; got {uri!r}")
    prefix = parsed.path.strip("/")
    return parsed.netloc, f"{prefix}/" if prefix else ""


def sha256_b64(path: Path) -> str:
    """The file's SHA-256, base64-encoded as S3 reports it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return base64.b64encode(digest.digest()).decode()


def cell_files(cell_dir: Path) -> list[Path]:
    """Every file in a cell directory, data first and :data:`LAST` at the end."""
    files = sorted(p for p in cell_dir.rglob("*") if p.is_file())
    order = {name: i for i, name in enumerate(LAST, start=1)}
    return sorted(files, key=lambda p: order.get(p.relative_to(cell_dir).as_posix(), 0))


def remote_sha256(client, bucket: str, key: str) -> str | None:
    """The stored object's SHA-256, ``""`` if it has none, or ``None`` if it is absent."""
    try:
        head = client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return head.get("ChecksumSHA256", "")


def upload_cell(client, bucket: str, prefix: str, cell_dir: Path, dry_run: bool) -> list[Entry]:
    """Upload one cell folder, or report what would happen when ``dry_run``."""
    folder = f"{prefix}{cell_dir.name}/"
    planned = []
    for path in cell_files(cell_dir):
        key = f"{folder}{path.relative_to(cell_dir).as_posix()}"
        size, local = path.stat().st_size, sha256_b64(path)
        if size > MAX_PUT_BYTES:
            return [Entry(key, size, local, ERROR, "larger than a single PUT allows")]
        remote = remote_sha256(client, bucket, key)
        if remote is None:
            planned.append((path, Entry(key, size, local, WOULD_UPLOAD)))
        elif remote == local:
            planned.append((path, Entry(key, size, local, SKIPPED)))
        else:
            reason = "exists with different content" if remote else "exists with no checksum"
            planned.append((path, Entry(key, size, local, CONFLICT, reason)))

    if dry_run or any(entry.status == CONFLICT for _, entry in planned):
        return [entry for _, entry in planned]

    done = []
    for path, entry in planned:
        if entry.status == SKIPPED:
            done.append(entry)
            continue
        try:
            client.put_object(
                Bucket=bucket,
                Key=entry.key,
                Body=path.read_bytes(),
                IfNoneMatch="*",
                ChecksumSHA256=entry.sha256,
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            status = CONFLICT if code == "PreconditionFailed" else ERROR
            done.append(Entry(entry.key, entry.size, entry.sha256, status, code))
            break
        done.append(Entry(entry.key, entry.size, entry.sha256, UPLOADED))
    return done


def upload_cells(
    client, destination: str, cell_dirs: list[Path], mode: str, manifest: Path
) -> bool:
    """Upload every cell, write the manifest, and return whether all of it succeeded.

    The manifest is written even when an unexpected error (e.g. access denied) stops the
    run, so it always records what was written before that.
    """
    bucket, prefix = parse_destination(destination)
    dry_run = mode == DRY_RUN
    entries: list[Entry] = []
    try:
        for cell_dir in cell_dirs:
            cell = upload_cell(client, bucket, prefix, cell_dir, dry_run)
            entries.extend(cell)
            bad = [e for e in cell if e.status in (CONFLICT, ERROR)]
            if bad:
                logger.error("%s: not uploaded (%s: %s)", cell_dir.name, bad[0].key, bad[0].detail)
            else:
                logger.info("%s: %d file(s) %s", cell_dir.name, len(cell), mode)
    finally:
        manifest.write_text(
            json.dumps(
                {"destination": f"s3://{bucket}/{prefix}", "mode": mode,
                 "files": [asdict(e) for e in entries]},
                indent=2,
            ),
            encoding="utf-8",
        )
    return not any(e.status in (CONFLICT, ERROR) for e in entries)
