#!/usr/bin/env bash
# Run a command in CI. If it fails, also report the end of its output as a
# GitHub annotation, so the error is visible on the pull request without
# opening the full log.
#   tools/ci_run.sh "Step name" command args...
title="$1"; shift
out="$(mktemp)"
set +e
"$@" 2>&1 | tee "$out"
status=${PIPESTATUS[0]}
set -e
if [ "$status" -ne 0 ]; then
  msg="$(tail -n 60 "$out" | sed -e 's/%/%25/g' | awk 'BEGIN{ORS="%0A"} {gsub(/\r/,""); print}')"
  echo "::error title=${title} failed (exit ${status})::${msg}"
fi
rm -f "$out"
exit "$status"
