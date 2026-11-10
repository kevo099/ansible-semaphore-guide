#!/usr/bin/env bash
# Moved: this is now controller/add-target.sh. This wrapper stays for one release,
# because VMs prepared with earlier copies of the onboarding files still print
# "sudo bash scripts/add-target.sh --from-info". It only passes its options on.
set -euo pipefail
exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/../controller/add-target.sh" "$@"
