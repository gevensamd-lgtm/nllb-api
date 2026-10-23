ARG PYTHON_VERSION_TAG=3.14

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv_binary
FROM rust:1.99.1-slim-trixie@sha256:aab42391a986424e22d6a3ec14f37bc6dd3dacff4d457ca7cccd781e02297cc6 AS rust_toolchain

FROM python:3.14.9-slim-trixie@sha256:b347e2dcbc7f0b6f9fb7182e9da6a187fb10ae715e0692518c1aed0eec94a700 AS model-builder

RUN apt-get update && apt-get -y --no-remove upgrade \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.2
COPY scripts/prune_retired_ca.py /usr/local/libexec/prune_retired_ca.py
RUN --network=none python /usr/local/libexec/prune_retired_ca.py
COPY requirements-models.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-models.lock
COPY server/model_integrity.py /opt/model_integrity.py
RUN python /opt/model_integrity.py


FROM python:3.14.9-trixie@sha256:2c90493710bd462e097441e60b0218430d8f7e2b46779bfca3742b2efd386feb AS python-builder

ARG USE_CUDA=0

WORKDIR /home/nonroot

ENV UV_LINK_MODE=copy
ENV UV_NO_CACHE=1
ENV UV_NO_DEV=1
ENV UV_LOCKED=1
ENV UV_NO_EDITABLE=1
ENV PYTHONOPTIMIZE=2
ENV RUSTFLAGS="-C target-cpu=native"
ENV CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup RUSTUP_TOOLCHAIN=1.99.1
ENV PATH=/usr/local/cargo/bin:$PATH
ENV UV_PYTHON_DOWNLOADS=never CARGO_BUILD_JOBS=2

RUN apt-get update && apt-get -y --no-remove upgrade \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.2
COPY scripts/prune_retired_ca.py /usr/local/libexec/prune_retired_ca.py
RUN --network=none python /usr/local/libexec/prune_retired_ca.py
COPY --from=uv_binary /uv /bin/
COPY --from=rust_toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust_toolchain /usr/local/rustup /usr/local/rustup
COPY pyproject.toml uv.lock ./
COPY client client
COPY language language

RUN case "$USE_CUDA" in \
    0) uv sync --frozen --no-install-project ;; \
    1) uv sync --frozen --no-install-project --extra cuda ;; \
    *) echo 'USE_CUDA must be 0 or 1' >&2; exit 1 ;; \
    esac

COPY server server

RUN case "$USE_CUDA" in \
    0) uv sync --frozen ;; \
    1) uv sync --frozen --extra cuda ;; \
    *) echo 'USE_CUDA must be 0 or 1' >&2; exit 1 ;; \
    esac
RUN uv pip check
RUN find .venv /usr/local/lib -name '*.so*' -type f -exec strip --strip-unneeded {} + 2>/dev/null


FROM gcr.io/distroless/python3-debian13:nonroot@sha256:727eccc5d83f11273c954652667b5b5a1c66120bd4cfb884e879ab77dcdf966a AS distroless
FROM busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e AS distroless-trimmed

COPY --from=distroless / /distroless/
RUN rm -rf /distroless/usr/bin/python3* /distroless/usr/lib/python3* \
    /distroless/etc/ssl/certs /distroless/usr/share/ca-certificates /distroless/usr/lib/ssl


FROM scratch

ARG PYTHON_VERSION_TAG
ARG USE_CUDA=False

ENV HOME=/home/nonroot
ENV PATH=$HOME/.venv/bin:/usr/local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_NO_ADVISORY_WARNINGS=1
ENV USE_CUDA=$USE_CUDA
ENV LD_LIBRARY_PATH=/usr/local/lib:$HOME/.venv/lib/python$PYTHON_VERSION_TAG/site-packages/nvidia/cublas/lib

COPY --from=distroless-trimmed /distroless/ /
COPY --from=model-builder --chown=65532:65532 /root/.cache/huggingface $HOME/.cache/huggingface
COPY --from=python-builder     /usr/local/lib/libpython* /usr/local/lib/
COPY --from=python-builder     /usr/local/lib/python$PYTHON_VERSION_TAG /usr/local/lib/python$PYTHON_VERSION_TAG
COPY --from=python-builder     /usr/local/bin/python$PYTHON_VERSION_TAG /usr/local/bin/
COPY --from=python-builder     /usr/local/bin/python3 /usr/local/bin/
COPY --from=python-builder     /usr/lib/ssl /usr/lib/ssl
COPY --from=python-builder     /etc/ssl/certs /etc/ssl/certs
COPY --from=python-builder     /usr/share/ca-certificates /usr/share/ca-certificates
COPY --from=python-builder     $HOME/.venv $HOME/.venv

USER nonroot
CMD ["nllb-api"]

# Preserve deployment defaults from the original root wrapper.

ENV SERVER_PORT=7860
ENV TRANSLATOR_THREADS=4

ENV OMP_NUM_THREADS=1
ENV CT2_USE_EXPERIMENTAL_PACKED_GEMM=1
ENV CT2_FORCE_CPU_ISA=AVX512

ENV OTEL_SEMCONV_STABILITY_OPT_IN=http
ENV CONSUL_SERVICE_ADDRESS=winstxnhdw-nllb-api.hf.space

EXPOSE $SERVER_PORT
