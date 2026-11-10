"""Upload packaged cells to S3, one folder per cell."""

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

DRY_RUN = "dry_run"
JSON = "application/json"
BINARY = "application/octet-stream"


def content_type(path: Path) -> str:
    """JSON for metadata and the ``info`` files of precomputed sources; bytes otherwise."""
    return JSON if path.suffix == ".json" or path.name == "info" else BINARY


def upload_cells(client, destination: str, cell_dirs: list[Path], manifest: Path) -> bool:
    """Write each cell's files under ``destination``, or only list them if it is blank."""
    parsed = urlparse(destination)
    bucket, prefix = parsed.netloc, parsed.path.strip("/")
    results = {}
    for cell_dir in cell_dirs:
        for path in sorted(p for p in cell_dir.rglob("*") if p.is_file()):
            parts = [prefix, cell_dir.name, path.relative_to(cell_dir).as_posix()]
            key = "/".join(part for part in parts if part)
            results[key] = _put(client, bucket, key, path) if destination else DRY_RUN
    manifest.write_text(json.dumps({"destination": destination, "files": results}, indent=2))
    failed = [key for key, status in results.items() if status not in (DRY_RUN, "uploaded")]
    for key in failed:
        logger.error("Not uploaded: s3://%s/%s (%s)", bucket, key, results[key])
    if destination:
        logger.info("Uploaded %d file(s) to %s", len(results) - len(failed), destination)
    else:
        logger.info("Dry run: no s3_destination; %d file(s) listed in %s", len(results), manifest)
    return not failed


def _put(client, bucket: str, key: str, path: Path) -> str:
    """Write one file unless the key already exists."""
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=path.read_bytes(),
            ContentType=content_type(path),
            IfNoneMatch="*",
        )
    except ClientError as error:
        code = error.response["Error"]["Code"]
        return "exists" if code == "PreconditionFailed" else code
    return "uploaded"
