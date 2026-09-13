#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
PYTHONPATH=backend uv run python -m deadlock.api
