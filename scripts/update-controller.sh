#!/usr/bin/env bash
# Moved: this is now controller/update-controller.sh. This wrapper stays for one
# release, because the update steps of releases up to v1.8.0 name this path in the
# newer copy of the guide. It only passes its options on.
set -euo pipefail
exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/../controller/update-controller.sh" "$@"
