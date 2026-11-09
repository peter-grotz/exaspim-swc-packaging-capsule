# exaspim-swc-packaging-capsule

Terminal stage of the exaSPIM SWC processing pipeline. Regroups the pipeline's outputs
into one AIND derived data asset per reconstruction.

## Usage

Reads the upstream stage outputs mounted at `/data` and writes one directory per cell to
`/results`, each containing the reconstructions plus `data_description.json` and
`processing.json`. A cell also gets `quality_control.json` when a QC record for it is found
anywhere under `/data` (any `*quality_control*.json`, matched to the cell by each metric's
`swc` tag); a cell without one is still packaged, with a warning. Folder names use Pacific
time.

Parameters are optional; the parent asset is inferred from the alignment stage's record
when not given.

### Upload to S3

With `s3_destination` set (e.g. `s3://aind-scratch-data/`), each cell folder is
uploaded as its own folder under it. `upload_mode` is `dry_run` by default, which reports
what would be written; `upload` writes it. Nothing is ever overwritten or deleted:

- a file that is absent is written with S3's conditional `IfNoneMatch`, and its SHA-256 is
  verified by S3 on receipt;
- a file already there with the same SHA-256 is skipped, so a rerun completes a partial
  upload;
- a file already there with other content, or with no checksum, is a conflict, and nothing
  in that cell is written.

`processing.json` and `data_description.json` go up last, so a folder without
`data_description.json` is incomplete. Every run writes `upload_manifest.json` to `/results`
with each key, size, SHA-256 and outcome, and exits non-zero on any conflict or error.
Writes use the AWS credentials attached to the capsule.

## Level of Support

![support](https://img.shields.io/badge/support-supported-brightgreen)

## Installation

All logic lives in [exaspim-swc-processing](https://github.com/AllenNeuralDynamics/exaspim-swc-processing),
installed by `environment/Dockerfile`. This capsule reads the Code Ocean inputs, calls the
library, and uploads the result.
