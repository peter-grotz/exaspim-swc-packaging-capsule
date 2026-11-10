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

Each reconstruction folder also gets a Neuroglancer precomputed skeleton source, holding the
reconstruction as segment `1`. Files are named `<neuron>-<subject>`, without the annotator
initials, so `N024-841260-DR.swc` is packaged as `N024-841260.swc`:

```
<asset>/
  ccf_space_reconstructions/N024-841260.swc
  ccf_space_reconstructions/reconstructions.precomputed/        # from the CCF SWC
  specimen_space_reconstructions/N024-841260.swc                # resampled (main)
  specimen_space_reconstructions/N024-841260_dense.swc          # refined
  specimen_space_reconstructions/reconstructions.precomputed/   # from the resampled SWC
  raw_reconstructions/N024-841260.swc                           # from refinement/raw
  raw_reconstructions/reconstructions.precomputed/              # from the raw SWC
  data_description.json  processing.json  quality_control.json
```

A raw reconstruction is packaged only alongside the neuron's other reconstructions: one with
no refined or CCF tracing does not get an asset of its own.

The conversion is recorded in `processing.json` as `precomputed_conversion` (File format
conversion).

Parameters are optional; the parent asset is inferred from the alignment stage's record
when not given.

### Quality control links

QC runs before packaging, so its Neuroglancer references (`js:neuroglancer?skeleton=...`)
can only name the skeleton source relative to the asset, e.g.
`skeleton=ccf_space_reconstructions/reconstructions.precomputed` (the QC capsule's
`asset_skeleton` setting). Packaging rewrites each one to
`s3://<s3_destination>/<asset>/...` with `segments=1`. A link to a source the cell lacks is
removed. In a dry run the links stay relative.

### Upload to S3

Set `s3_destination` (e.g. `s3://aind-open-data/`) to upload each cell folder under it.
Left blank, the run is a dry run: nothing is written to S3. Either way, `upload_manifest.json`
in `/results` lists every file's key and outcome. `info` and `.json` files are uploaded as
`application/json`.

Neuroglancer loads the skeletons from the browser, without credentials. The QC links
therefore only open when the destination is publicly readable and allows CORS `GET`, as
`aind-open-data` does. On a private bucket such as `aind-scratch-data` the links resolve
but don't load.

## Level of Support

![support](https://img.shields.io/badge/support-supported-brightgreen)

## Installation

All logic lives in [exaspim-swc-processing](https://github.com/AllenNeuralDynamics/exaspim-swc-processing),
installed by `environment/Dockerfile`. This capsule reads the Code Ocean inputs, calls the
library, and uploads the result.
