# exaspim-swc-packaging-capsule

Terminal stage of the exaSPIM SWC processing pipeline. Regroups the pipeline's outputs
into one AIND derived data asset per reconstruction.

## Usage

Reads the upstream stage outputs mounted at `/data` and writes one directory per cell to
`/results`, each containing the reconstructions plus `data_description.json` and
`processing.json`. A cell also gets `quality_control.json` when a QC record for it is found
anywhere under `/data` (any `*quality_control*.json`, matched to the cell by each metric's
`swc` tag); a cell without one is still packaged, with a warning. A
`packaging_summary.json` at the results root lists what was packaged and what was skipped.

Parameters are optional; the parent asset is inferred from the alignment stage's record
when not given.

## Level of Support

![support](https://img.shields.io/badge/support-supported-brightgreen)

## Installation

All logic lives in [exaspim-swc-processing](https://github.com/AllenNeuralDynamics/exaspim-swc-processing),
installed by `environment/Dockerfile`. This capsule contains only Code Ocean glue.
