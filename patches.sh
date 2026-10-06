#!/usr/bin/env bash
# Discover and apply optional end4-pC patches from this directory.

set -euo pipefail

script_dir="$(dirname "$(readlink -f "$0")")"
repo="${END4_REPO:-$HOME/.config/quickshell/end4-pC}"
bin_dir="${END4_BIN_DIR:-$HOME/.local/bin}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

usage() {
    printf 'Usage: %s [list|select|apply|remove] [patch ...]\n' "${0##*/}"
    printf 'Set END4_REPO to use a repository other than ~/.config/quickshell/end4-pC.\n'
    printf 'Set END4_BIN_DIR to install helpers somewhere other than ~/.local/bin.\n'
}

patches=()
while IFS= read -r -d '' patch; do
    patches+=("$patch")
done < <(printf '%s\0' "$script_dir"/*.patch)

if [[ ${patches[0]:-} == "$script_dir/*.patch" ]]; then
    printf 'No patch files found in %s\n' "$script_dir" >&2
    exit 1
fi

require_repo() {
    git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
        printf 'end4-pC repository not found: %s\n' "$repo" >&2
        exit 1
    }
}

patch_name() {
    basename "$1" .patch
}

is_directly_installed() {
    local patch=$1 marker_file marker_text

    if [[ -f "$patch.markers" ]]; then
        while IFS=: read -r marker_file marker_text; do
            [[ -n $marker_file && -n $marker_text && -f "$repo/$marker_file" ]] || return 1
            grep -Fq -- "$marker_text" "$repo/$marker_file" || return 1
        done < "$patch.markers"
        return 0
    fi

    git -C "$repo" apply --3way --reverse --check --recount "$patch" >/dev/null 2>&1
}

is_installed() {
    local patch=$1 candidate dependency

    is_directly_installed "$patch" && return 0
    for candidate in "${patches[@]}"; do
        [[ $candidate == "$patch" || ! -f "$candidate.deps" ]] && continue
        while IFS= read -r dependency; do
            [[ $dependency == "$(patch_name "$patch")" ]] && is_directly_installed "$candidate" && return 0
        done < "$candidate.deps"
    done
    return 1
}

show_patches() {
    local patch state
    for patch in "${patches[@]}"; do
        state='not installed'
        is_installed "$patch" && state='installed'
        printf '%-32s %s\n' "$(patch_name "$patch")" "$state"
    done
}

resolve_patch() {
    local requested=$1 patch
    for patch in "${patches[@]}"; do
        if [[ $requested == "$(patch_name "$patch")" || $requested == "$(basename "$patch")" ]]; then
            printf '%s\n' "$patch"
            return 0
        fi
    done
    printf 'Unknown patch: %s\n' "$requested" >&2
    return 1
}

install_helpers() {
    local patch=$1 helper

    [[ -f "$patch.scripts" ]] || return 0
    while IFS= read -r helper; do
        [[ -n $helper && -f "$script_dir/$helper" ]] || {
            printf 'Missing helper for %s: %s\n' "$(patch_name "$patch")" "$helper" >&2
            return 1
        }
        install -Dm755 "$script_dir/$helper" "$bin_dir/$helper"
        printf 'Installed helper %s to %s\n' "$helper" "$bin_dir"
    done < "$patch.scripts"
}

install_units() {
    local patch=$1 unit units=()
    [[ -f "$patch.units" ]] || return 0
    mkdir -p "$unit_dir"
    while IFS= read -r unit; do
        [[ -n $unit && -f "$script_dir/$unit" ]] || return 1
        python3 - "$script_dir/$unit" "$unit_dir/$unit" "$bin_dir" <<'PY'
import sys
from pathlib import Path
source, destination, bin_dir = sys.argv[1:]
bin_dir = str(Path(bin_dir).resolve()).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
Path(destination).write_text(Path(source).read_text().replace('@BIN_DIR@', bin_dir))
PY
        units+=("$unit")
    done < "$patch.units"
    systemctl --user daemon-reload
    systemctl --user enable "${units[@]}"
    # Start sockets first, then reload workers after installing their helpers.
    for unit in "${units[@]}"; do
        if [[ $unit == *.service ]]; then
            systemctl --user restart "$unit"
        else
            systemctl --user start "$unit"
        fi
    done
}

remove_units() {
    local patch=$1 unit units=()
    [[ -f "$patch.units" ]] || return 0
    while IFS= read -r unit; do
        [[ -n $unit ]] && units+=("$unit")
    done < "$patch.units"
    systemctl --user disable --now "${units[@]}"
    for unit in "${units[@]}"; do
        rm -f "$unit_dir/$unit"
    done
    systemctl --user daemon-reload
}

apply_one() {
    local patch=$1 dependency upgrade
    install_helpers "$patch"
    # Upgrade an older installed variant without touching other local patches.
    for upgrade in "$patch.upgrade" "$patch.upgrade."*; do
        if [[ -f "$upgrade" ]] && git -C "$repo" apply --check "$upgrade" >/dev/null 2>&1; then
            git -C "$repo" apply --3way "$upgrade"
            printf 'Upgraded %s\n' "$(patch_name "$patch")"
        fi
    done
    if is_installed "$patch"; then
        printf '%s is already installed\n' "$(patch_name "$patch")"
    else
        if [[ -f "$patch.deps" ]]; then
            while IFS= read -r dependency; do
                [[ -n $dependency ]] && apply_one "$(resolve_patch "$dependency")"
            done < "$patch.deps"
        fi
        git -C "$repo" apply --3way --recount "$patch"
        printf 'Installed %s\n' "$(patch_name "$patch")"
    fi
    install_units "$patch"
}

remove_one() {
    local patch=$1
    if is_directly_installed "$patch"; then
        git -C "$repo" apply --3way --reverse --recount "$patch"
        remove_units "$patch"
        printf 'Removed %s\n' "$(patch_name "$patch")"
    elif is_installed "$patch"; then
        printf '%s is required by an installed patch and cannot be removed yet\n' "$(patch_name "$patch")" >&2
        return 1
    else
        printf '%s is not installed\n' "$(patch_name "$patch")"
    fi
}

select_patches() {
    local action index=1 start end patch choice selected=() selected_state=() chosen=()

    printf 'Available patches:\n'
    for patch in "${patches[@]}"; do
        printf '  %d) %s' "$index" "$(patch_name "$patch")"
        is_installed "$patch" && printf ' [installed]'
        printf '\n'
        ((++index))
    done
    printf 'Action: [t]oggle, [i]nstall, [r]emove, [q]uit: '
    read -r action
    case "${action:-t}" in
        t|toggle|i|install|r|remove)
            ;;
        q|quit)
            return
            ;;
        *)
            printf 'Invalid action: %s\n' "$action" >&2
            exit 2
            ;;
    esac

    printf 'Choose numbers or ranges, e.g. 1 3-5 (empty to cancel): '
    read -r -a choice
    for choice in "${choice[@]}"; do
        if [[ $choice =~ ^([0-9]+)-([0-9]+)$ ]]; then
            start=${BASH_REMATCH[1]}
            end=${BASH_REMATCH[2]}
        elif [[ $choice =~ ^[0-9]+$ ]]; then
            start=$choice
            end=$choice
        else
            printf 'Invalid patch selection: %s\n' "$choice" >&2
            exit 2
        fi

        [[ $start -ge 1 && $end -le ${#patches[@]} && $start -le $end ]] || {
            printf 'Invalid patch range: %s\n' "$choice" >&2
            exit 2
        }
        for ((index = start; index <= end; index++)); do
            [[ ${chosen[index]:-0} == 1 ]] && continue
            chosen[index]=1
            selected+=("${patches[index - 1]}")
        done
    done

    case "$action" in
        i|install)
            for patch in "${selected[@]}"; do
                apply_one "$patch"
            done
            ;;
        r|remove)
            # Remove in reverse order so dependents are removed before providers.
            for ((index = ${#selected[@]} - 1; index >= 0; index--)); do
                remove_one "${selected[index]}"
            done
            ;;
        *)
            for patch in "${selected[@]}"; do
                if is_installed "$patch"; then
                    selected_state+=(1)
                else
                    selected_state+=(0)
                fi
            done

            # Remove in reverse order so selected dependents are removed before providers.
            for ((index = ${#selected[@]} - 1; index >= 0; index--)); do
                if [[ ${selected_state[index]} == 1 ]]; then
                    remove_one "${selected[index]}"
                fi
            done
            for index in "${!selected[@]}"; do
                if [[ ${selected_state[index]} == 0 ]]; then
                    apply_one "${selected[index]}"
                fi
            done
            ;;
    esac
}

require_repo
case "${1:-select}" in
    list)
        [[ $# == 1 ]] || { usage >&2; exit 2; }
        show_patches
        ;;
    select)
        [[ $# == 0 || $# == 1 ]] || { usage >&2; exit 2; }
        select_patches
        ;;
    apply|remove)
        action=$1
        shift
        (($#)) || { usage >&2; exit 2; }
        for requested in "$@"; do
            patch="$(resolve_patch "$requested")"
            "${action}_one" "$patch"
        done
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
