"""Package exaSPIM SWC pipeline outputs into one AIND derived asset per reconstruction.

Code Ocean glue only. Everything substantive lives in ``exaspim-swc-processing``; this
reads the capsule's inputs, calls the library, and reports what happened.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from aind_data_schema.components.identifiers import Code
from aind_data_schema.core.processing import DataProcess

from exaspim_swc_processing.packaging import build_packaging_process, package_cells
from exaspim_swc_processing.parent_metadata import (
    ParentMetadataNotFoundError,
    resolve_parent_metadata,
)
from exaspim_swc_processing.sources import default_sources, upgrade_data_description

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/results"))
STAGE_DIRS = ("dispatch", "refinement", "alignment", "final")

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
    parser.add_argument("--experimenters", default=os.environ.get("EXPERIMENTERS", ""))
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


def infer_parent_asset(processes: list[DataProcess]) -> str:
    """Recover the parent asset name from the alignment stage's parameters.

    The transform stage records the S3 prefix it staged registration files from, so the
    parent does not need to be passed in separately.

    Parameters
    ----------
    processes : list[DataProcess]
        Stage records.

    Returns
    -------
    str
        The parent asset name, or an empty string if it cannot be recovered.
    """
    for process in processes:
        parameters = getattr(process.code, "parameters", None)
        values = parameters.model_dump() if hasattr(parameters, "model_dump") else parameters
        dataset = (values or {}).get("processed_dataset", "")
        if dataset:
            return str(dataset).rstrip("/").removeprefix("s3://").split("/", 1)[-1].split("/")[0]
    return ""


def run() -> int:
    """Package the run's reconstructions.

    Returns
    -------
    int
        Process exit status. Non-zero when no parent metadata could be found.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    started = datetime.now(timezone.utc)

    stage_processes = load_stage_processes(DATA_DIR)
    parent_asset = args.parent_asset or infer_parent_asset(stage_processes)
    if not parent_asset:
        logger.error("No parent asset given and none could be inferred from the stage records")
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

    experimenters = [e.strip() for e in args.experimenters.split(",") if e.strip()]

    def describe_packaging(finished: datetime) -> DataProcess:
        """Record this packaging step once the work has finished.

        Parameters
        ----------
        finished : datetime
            When packaging finished.

        Returns
        -------
        DataProcess
            The step record embedded in every cell.
        """
        return build_packaging_process(
            parent,
            pipeline,
            start_time=started,
            end_time=finished,
            output_path=".",
            **({"experimenters": experimenters} if experimenters else {}),
        )

    result = package_cells(
        DATA_DIR,
        RESULTS_DIR,
        parent,
        stage_processes,
        pipeline,
        creation_time=started,
        describe_packaging=describe_packaging,
        overrides=overrides,
    )

    summary = {
        "parent_asset": parent_asset,
        "metadata_source": parent.source.value,
        "packaged": [cell.asset_name for cell in result.packaged],
        "skipped": [
            {"reconstruction": cell.reconstruction.stem, "reason": cell.reason}
            for cell in result.skipped
        ],
    }
    (RESULTS_DIR / "packaging_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    logger.info("Packaged %d cell(s), skipped %d", len(result.packaged), len(result.skipped))
    return 0


if __name__ == "__main__":
    sys.exit(run())
