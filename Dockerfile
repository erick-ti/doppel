# Doppel application image — serves the FastAPI API and runs the ARQ worker (both embed previews, so
# the heavy `clap` group is installed). The migrate one-shot runs from the same image.
#
# NOTE: the `clap` group pulls torch/transformers, so this build is large and slow (multi-GB
# download). It is wired for the Day-7 VPS deploy and validated there; `docker compose config`
# verifies the compose wiring without building.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# libgomp1 is the OpenMP runtime the CPU PyTorch wheels link against. PyAV (av) and transformers ship
# self-contained wheels, so no system ffmpeg is required.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies first (this layer is cached unless pyproject.toml / uv.lock change), then the
# project. `--group clap` installs core + the heavy audio stack; the `dev` group is omitted.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --group clap
COPY . .
RUN uv sync --frozen --group clap

# Default command is the API; the worker and migrate compose services override it. Migrations are an
# explicit step (the one-shot `migrate` service), never an app/worker entrypoint (Invariant #3).
EXPOSE 8000
CMD ["uvicorn", "doppel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
