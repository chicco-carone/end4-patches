#!/usr/bin/env bash
# Reapply the display-mode button patch across end4-pC updates.

set -euo pipefail

repo="${END4_REPO:-$HOME/.config/quickshell/end4-pC}"
patch="$(dirname "$(readlink -f "$0")")/display-mode.patch"

usage() {
    printf 'Usage: %s {apply|remove|update}\n' "${0##*/}"
}

apply_patch() {
    "$(dirname "$patch")/patches.sh" apply display-mode
}

remove_patch() {
    "$(dirname "$patch")/patches.sh" remove display-mode
}

case "${1:-apply}" in
    apply)
        apply_patch
        ;;
    remove)
        remove_patch
        ;;
    update)
        remove_patch
        if ! git -C "$repo" pull --ff-only; then
            apply_patch
            exit 1
        fi
        apply_patch
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
