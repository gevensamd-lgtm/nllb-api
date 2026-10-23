# Dependency refresh — 22 October 2026

The Python dependency cohort includes certifi 2026.10.19 and current aiohttp,
HTTP clients, telemetry packages, build tools and development tools. Regenerate
both uv lockfiles with uv 0.13.5 and retain frozen installation checks. Runtime
and development audits must both be reviewed; a clean source manifest does not
update an already running image.

This project currently requires Python >=3.14.6,<3.15. CTranslate2 4.8.3 has
neither CPython 3.15 nor stable-ABI wheels in the metadata checked on 22 October.
Review upstream support and the local Rust extension before lifting that limit.
Fast-query-parsers 1.0.3 does publish stable-ABI wheels and is not that blocker.
Fasttext 0.9.3 has no Linux wheels for either Python 3.14 or 3.15, so Linux
installation already requires a reviewed source build. Absence of its cp315
wheel alone does not demonstrate Python 3.15 incompatibility. A failed
binary-only resolver must not be replaced by an unreviewed source build simply
to claim Python 3.15.

The old development-only nodejs-wheel-binaries package publishes Node 24.19.0,
which predates the current security fixes. It is removed from the development
group. Use the official Node 26.12.1 selected by `.nvmrc` on PATH when running
Pyright; do not activate Pyright's optional `nodejs`/`all` extra, which would
reintroduce that binary distribution. The ordinary Pyright package can use the
existing Node executable.

The root `Dockerfile` now builds the reviewed fork directly: its complete
build recipe is an exact prefix copy of `Dockerfile.build`. A default
`docker build .` therefore uses the pinned interpreter, TLS stores, locks and
model verification described below, rather than the old floating upstream
`main` image. Keep those two build recipes synchronized when changing them.

The root file then retains all seven original deployment variables and
`EXPOSE $SERVER_PORT`: port 7860, four translator threads, OMP_NUM_THREADS=1,
experimental packed GEMM, CT2_FORCE_CPU_ISA=AVX512, HTTP telemetry semantics and
the existing Consul service address. Authorization and route defaults still
come from the unchanged application configuration. Setting a Consul service
address alone does not register a service: CONSUL_HTTP_ADDR is unset by default
and both values are required. Deployment overrides remain possible. The
AVX512 setting requires a compatible deployment CPU; the native offline
configuration canary verifies this setting on the reviewed AMD64 host.

`Dockerfile.build` pins Python 3.14.9, uv 0.13.5 and Rust 1.99.1 by official
image digest. The Rust extension selects that stable toolchain explicitly;
the old moving nightly selection is removed. CPU builds now install only
the CPU dependencies: the previous nonempty string `USE_CUDA=0` accidentally
enabled the CUDA extra. Only explicit build argument values 0 and 1 are
accepted. The interpreter and libpython come from the same builder.

The distroless base and BusyBox 1.37.0 trimming stage have immutable digests.
BusyBox's official `stable` alias still points to 1.36.1; 1.38.0 is marked
unstable in the checked official image metadata. The trimming utility is not
copied to the final image. Updated OS CA files are copied from the Python
builder to match the OpenSSL default trust path; verify the effective final
image truststore before rollout.

Generate the independent model-download lock with uv 0.13.5:

```sh
uv pip compile requirements-models.in --generate-hashes --python-version 3.14 --output-file requirements-models.lock
pip-audit -r requirements-models.lock --no-deps --disable-pip
```

Model downloads now use the two production-inventoried immutable revisions:
`5d67ab73ef26497a7964712d7df01dfa1569dd04` (translation) and
`3af127d4124fc58b75666f3594bb5143b9757e78` (language identification). Seven
artifact SHA256 hashes are verified in the model builder and at runtime; a
mutation regression checks rejection of an altered file. The original model
weights are preserved. The runtime cache belongs to UID 65532 so the nonroot
application can read Hugging Face tree-cache files.

Rust dependencies now use PyO3/PyO3-build-config 0.30.1, Tokio 1.54.1 and
Reqwest 0.13.5. PyO3 drops Python 3.8; the standalone client's minimum is 3.9.
Its module initializer uses the supported zero-argument form, and obsolete
3.8 cfg checks are removed while preserving behavior for supported versions.
Both Maturin builds enforce Cargo.lock. Production/development native builds
and pip check pass. Cargo audit 0.22.2 reports zero vulnerabilities and zero
informational warnings in the client lock (174 dependencies) and language lock (141 dependencies). Cargo test --lib compiles both targets successfully; these targets have
no Rust unit tests, so behavioral evidence comes from API/client/model gates.

A native AMD64 final image passed real translation (single/batch), language
detection, forced Lingua fallback and token-count requests with networking
disabled, the pinned artifacts and synthetic inputs only. The final refreshed
image and regression gates must be reviewed before publication/deployment.

The native client query serializer now uses the documented hyphenated
threshold aliases, matching Litestar's query parameters. A synthetic local
HTTP server captures requests from both sync and async Rust clients; the
regression failed against the previous underscore names and passes with
explicit Serde renames. Public Python argument names and threshold bounds
are unchanged. The client CI matrix no longer advertises Python 3.8.

The standalone client wheel is a development dependency of the API project
and is tested independently. It is not installed in the production server
image. Pytest gates explicitly set PYTHONOPTIMIZE=0 so fixture/helper
assertions remain active; test assertions and warnings are enforced.

The root-default deployment overlay passed an additional native AMD64 canary
on the verified base image `sha256:4d73dc77fd9186f201044f96351f360ef778467c130464ae236e9d2a9142bae3`.
The root recipe prefix and all inputs of that image were checked byte-for-byte;
only the preserved environment and EXPOSE metadata were applied for this gate.
With network none, 2 CPUs, 8 GiB and no additional swap, it served real HTTP
health, English/Spanish detection, forced Lingua fallback, single/batch
translation and token counts on port 7860 with AVX512. The original `/api`
prefix, four translator threads, UID 65532 and all seven model hashes/revisions
were retained. Default Consul registration stayed disabled without
CONSUL_HTTP_ADDR. Peak memory was 5,474,422,784 bytes with zero OOM/max events.
The canary exited normally with RC0 and its labelled container was removed.
This configuration gate reuses the reviewed native image; it does not claim a
second full source build or rerun the 137 unchanged regression tests.
