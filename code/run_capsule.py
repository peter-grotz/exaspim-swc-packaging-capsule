"""Package exaSPIM SWC pipeline outputs into one AIND derived asset per reconstruction.

Reads the capsule's inputs, calls ``exaspim-swc-processing``, which does the packaging, and
optionally uploads each cell folder to S3 (see :mod:`upload`).
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3

from aind_data_schema.components.identifiers import Code
from aind_data_schema.core.processing import DataProcess

from exaspim_swc_processing.packaging import package_cells
from exaspim_swc_processing.parent_metadata import (
    ParentMetadataNotFoundError,
    resolve_parent_metadata,
)
from exaspim_swc_processing.quality_control import discover_quality_control
from exaspim_swc_processing.sources import default_sources, upgrade_data_description
from exaspim_swc_processing.stage import PROCESSED_DATASET_FILE
from upload import DRY_RUN, MODES, upload_cells

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/results"))
STAGE_DIRS = ("dispatch", "refinement", "alignment", "final")
LOCAL_TIME = ZoneInfo("America/Los_Angeles")
"""Asset names use local time, per AIND naming; Pacific, wherever the capsule runs."""

logger = logging.getLogger("exaspim_swc_packaging")


def parse_args() -> argparse.Namespace:
    """Read the App Builder parameters.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent-asset",
        default=os.environ.get("PARENT_ASSET", ""),
        help="Name of the imaging asset the reconstructions derive from. Inferred from "
        "the alignment stage record when omitted.",
    )
    parser.add_argument(
        "--pipeline-url",
        default=os.environ.get("PIPELINE_URL", ""),
        help="Repository holding the Nextflow configuration.",
    )
    parser.add_argument("--pipeline-name", default=os.environ.get("PIPELINE_NAME", ""))
    parser.add_argument("--pipeline-version", default=os.environ.get("PIPELINE_VERSION", ""))
    parser.add_argument(
        "--modalities",
        default=os.environ.get("MODALITIES", "SPIM"),
        help="Comma-separated modality abbreviations, used when the parent omits them.",
    )
    parser.add_argument(
        "--s3-destination",
        default=os.environ.get("S3_DESTINATION", ""),
        help="s3://bucket/prefix/ to upload each cell folder under. Blank: no upload.",
    )
    parser.add_argument(
        "--upload-mode",
        default=os.environ.get("UPLOAD_MODE", "") or DRY_RUN,
        choices=MODES,
        help="dry_run reports what would be uploaded; upload writes it.",
    )
    return parser.parse_args()


def load_stage_processes(data_dir: Path) -> list[DataProcess]:
    """Read each stage's ``data_process.json`` from the mounted inputs.

    Parameters
    ----------
    data_dir : Path
        Directory the upstream stage outputs are mounted at.

    Returns
    -------
    list[DataProcess]
        The records found, in stage order.
    """
    processes = []
    for stage in STAGE_DIRS:
        path = data_dir / stage / "data_process.json"
        if not path.is_file():
            logger.warning("No data_process.json for stage %s", stage)
            continue
        processes.append(DataProcess.model_validate_json(path.read_text(encoding="utf-8")))
    return processes


def infer_parent_asset(data_dir: Path) -> str:
    """Read the parent dataset the transform applied, from its hand-off file.

    Parameters
    ----------
    data_dir : Path
        Directory the upstream stage outputs are mounted at.

    Returns
    -------
    str
        The parent asset name, or an empty string if the file is absent.
    """
    path = data_dir / "alignment" / PROCESSED_DATASET_FILE
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def run() -> int:
    """Package the run's reconstructions.

    Returns
    -------
    int
        Process exit status. Non-zero when no parent metadata could be found.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    started = datetime.now(LOCAL_TIME)

    stage_processes = load_stage_processes(DATA_DIR)
    parent_asset = args.parent_asset or infer_parent_asset(DATA_DIR)
    if not parent_asset:
        logger.error(
            "No parent asset given, and no alignment/%s from the transform", PROCESSED_DATASET_FILE
        )
        return 1
    logger.info("Parent asset: %s", parent_asset)

    try:
        parent = resolve_parent_metadata(parent_asset, default_sources(), upgrade_data_description)
    except ParentMetadataNotFoundError as error:
        logger.error("%s", error)
        return 1
    logger.info("Parent metadata from %s (upgraded=%s)", parent.source.value, parent.upgraded)

    pipeline = Code(
        url=args.pipeline_url or "https://github.com/peter-grotz/exaspim-swc-processing-pipeline",
        name=args.pipeline_name or "exaspim-swc-processing",
        version=args.pipeline_version or "0.0.0",
    )
    overrides: dict[str, object] = {}
    if not parent.data_description.modalities and args.modalities:
        overrides["modalities"] = [m.strip() for m in args.modalities.split(",") if m.strip()]

    quality_control = discover_quality_control(DATA_DIR)
    logger.info("Found quality control for %d cell(s)", len(quality_control))

    result = package_cells(
        DATA_DIR,
        RESULTS_DIR,
        parent,
        stage_processes,
        pipeline,
        creation_time=started,
        overrides=overrides,
        quality_control=quality_control,
    )

    for cell in result.skipped:
        logger.warning("Skipped %s: %s", cell.reconstruction.stem, cell.reason)
    with_qc = sum(cell.has_quality_control for cell in result.packaged)
    logger.info(
        "Packaged %d cell(s) (%d with quality control), skipped %d",
        len(result.packaged),
        with_qc,
        len(result.skipped),
    )

    if not args.s3_destination:
        return 0
    ok = upload_cells(
        boto3.client("s3"),
        args.s3_destination,
        [cell.directory for cell in result.packaged],
        args.upload_mode,
        RESULTS_DIR / "upload_manifest.json",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
