# hash:sha256:0000000000000000000000000000000000000000000000000000000000000000
ARG REGISTRY_HOST
FROM $REGISTRY_HOST/codeocean/mambaforge3:24.5.0-0-python3.12.4-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG GIT_ASKPASS
COPY git-ask-pass /

RUN pip install -U --no-cache-dir \
    # Pinned to a commit, not a branch: Docker keys this layer on the text of the
    # line, so '@dev' reuses a cached layer and silently installs nothing new.
    # Bump this SHA whenever the library changes.
    "exaspim-swc-processing @ git+https://github.com/peter-grotz/exaspim-swc-processing.git@dbfbb6543421f4271210067dd3e16514c296dae5"
