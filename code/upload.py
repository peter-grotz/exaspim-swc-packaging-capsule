"""Upload packaged cells to S3, one folder per cell."""

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

DRY_RUN, UPLOAD = "dry_run", "upload"
MODES = (DRY_RUN, UPLOAD)


def upload_cells(
    client, destination: str, cell_dirs: list[Path], mode: str, manifest: Path
) -> bool:
    """Write every file of every cell under ``destination``; return whether all succeeded."""
    parsed = urlparse(destination)
    bucket, prefix = parsed.netloc, parsed.path.strip("/")
    results = {}
    for cell_dir in cell_dirs:
        for path in sorted(p for p in cell_dir.rglob("*") if p.is_file()):
            parts = [prefix, cell_dir.name, path.relative_to(cell_dir).as_posix()]
            key = "/".join(part for part in parts if part)
            results[key] = DRY_RUN if mode == DRY_RUN else _put(client, bucket, key, path)
    manifest.write_text(json.dumps({"bucket": bucket, "mode": mode, "files": results}, indent=2))
    failed = [key for key, status in results.items() if status not in (DRY_RUN, "uploaded")]
    for key in failed:
        logger.error("Not uploaded: s3://%s/%s (%s)", bucket, key, results[key])
    logger.info("%d file(s) %s to s3://%s/%s", len(results) - len(failed), mode, bucket, prefix)
    return not failed


def _put(client, bucket: str, key: str, path: Path) -> str:
    """Write one file unless the key already exists."""
    try:
        client.put_object(Bucket=bucket, Key=key, Body=path.read_bytes(), IfNoneMatch="*")
    except ClientError as error:
        code = error.response["Error"]["Code"]
        return "exists" if code == "PreconditionFailed" else code
    return "uploaded"
