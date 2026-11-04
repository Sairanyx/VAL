#!/bin/bash
# Submission source .zip (required, <=100 MB, no deps/data). Uses git so .gitignore'd stuff is excluded.
set -euo pipefail
OUT=${1:-submission.zip}
git archive --format=zip -o "$OUT" HEAD
ls -lh "$OUT"
