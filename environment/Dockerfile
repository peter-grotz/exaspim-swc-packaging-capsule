# hash:sha256:0000000000000000000000000000000000000000000000000000000000000000
ARG REGISTRY_HOST
FROM $REGISTRY_HOST/codeocean/mambaforge3:24.5.0-0-python3.12.4-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG GIT_ASKPASS
COPY git-ask-pass /

# The library is pinned to a commit, not a branch: the layer is keyed on the text of
# this command, so '@dev' would reuse a cached layer and silently install nothing
# new. Bump the SHA whenever the library changes.
RUN pip install -U --no-cache-dir \
    "exaspim-swc-processing @ git+https://github.com/peter-grotz/exaspim-swc-processing.git@818a98aac7118257c201036405a09b09505d79ae"
