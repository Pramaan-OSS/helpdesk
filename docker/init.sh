#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'The upstream bootstrap was removed: it installed external phone software and fetched mutable source.' 'Use the verified startup instructions in DONE.md once local conversion checks are complete.' >&2
exit 1
