#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT"

echo "=========================================="
echo "Hyderabad Job Applications - LOCAL RUN"
echo "Started: $(date)"
echo "Root: $ROOT"
echo "=========================================="

powershell.exe \
  -NoProfile \
  -ExecutionPolicy Bypass \
  -File "$ROOT/run-local.ps1"

RC=$?

echo "=========================================="
echo "Finished: $(date)"
echo "Exit code: $RC"
echo "=========================================="

exit $RC