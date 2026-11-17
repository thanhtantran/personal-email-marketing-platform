#!/usr/bin/env bash
# Gentle Compose bring-up for Orange Pi when Docker root lives on NVMe.
# Build ONE backend image + ONE web image sequentially, then start without rebuild.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/infra/compose.yaml")
cd "$ROOT"

# Cap BuildKit parallelism (Compose still respects this for each build).
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"
export DOCKER_BUILDKIT=1
export BUILDKIT_STEP_LOG_MAX_SIZE="${BUILDKIT_STEP_LOG_MAX_SIZE:-1048576}"

BUILD_CPUSET="${BUILD_CPUSET:-0-1}"
BUILD_MEMORY="${BUILD_MEMORY:-4g}"
BUILD_MEMORY_SWAP="${BUILD_MEMORY_SWAP:-4g}"

echo "==> Prefetch pull-only images (no local Dockerfile build)"
"${COMPOSE[@]}" pull --quiet postgres redis object-storage || true

echo "==> Build backend image only (email-platform-api:local) on cpus ${BUILD_CPUSET}, mem ${BUILD_MEMORY}"
docker build \
  --network=host \
  --cpuset-cpus="${BUILD_CPUSET}" \
  --memory="${BUILD_MEMORY}" \
  --memory-swap="${BUILD_MEMORY_SWAP}" \
  -t email-platform-api:local \
  -f "$ROOT/infra/docker/Dockerfile.api" \
  "$ROOT"

echo "==> Pause 5s so NVMe settles"
sleep 5

echo "==> Build web image only (email-platform-web:local)"
docker build \
  --network=host \
  --cpuset-cpus="${BUILD_CPUSET}" \
  --memory="${BUILD_MEMORY}" \
  --memory-swap="${BUILD_MEMORY_SWAP}" \
  -t email-platform-web:local \
  -f "$ROOT/infra/docker/Dockerfile.web" \
  "$ROOT"

echo "==> Start stack WITHOUT rebuild (--no-build)"
"${COMPOSE[@]}" up -d --no-build

echo "==> Status"
"${COMPOSE[@]}" ps
