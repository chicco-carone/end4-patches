# end4-pC Local Patches

This folder contains optional local changes for `~/.config/quickshell/end4-pC`.

| Feature | Patch |
| --- | --- |
| Display refresh mode button | `display-mode.patch` |
| NetworkManager VPN button | `vpn-toggle.patch` |
| Peripheral battery indicator | `end4-peripheral-battery.patch` |
| G84 profile toggle | `g84-profile-toggle.patch` |
| Compact Codex usage indicator | `codex-usage.patch` |
| MPRIS Base64-encoded artwork in media controls | `mpris-vol.patch` |

## Use A Patch

Run the interactive selector to discover every `*.patch` in this directory. It
asks whether to install, remove, or toggle patches, then accepts numbers or
inclusive ranges such as `1 3-5`:

```bash
~/end4-patches/patches.sh
```

Use `patches.sh list` to show status, or `patches.sh apply NAME` and
`patches.sh remove NAME` for non-interactive use. Set `END4_REPO` when the
target repository is not `~/.config/quickshell/end4-pC`.

Selecting the display patch installs `ac-power-profile` into
`~/.local/bin` automatically. Ensure that directory is in `PATH`; set
`END4_BIN_DIR` to use another installation directory. Selecting the peripheral
battery and G84 toggle patches likewise installs `epomaker-battery` and
`g84-profile.py`; the peripheral patch still expects `mow` in `PATH`.
The VPN patch depends on the display patch; the selector installs that dependency
automatically.

The Codex usage indicator requires [`codexbar`](https://github.com/steipete/codexbar)
in `PATH`. Add **Codex Usage** to a bar layout in Settings, then hold it to show
the 5-hour and weekly reset details.

## Create A Patch

Create each optional feature from a clean temporary worktree at the same upstream revision as the dots. Do not include the source changes from other local patches in that worktree.

```bash
repo="$HOME/.config/quickshell/end4-pC"
tmp="/tmp/end4-my-feature"
git -C "$repo" worktree add --detach "$tmp" HEAD
# Edit the feature only in "$tmp".
git -C "$tmp" diff --binary > "$HOME/end4-patches/my-feature.patch"
git -C "$repo" worktree remove --force "$tmp"
```

`patches.sh` discovers new `.patch` files automatically. It uses `git apply
--3way` to tolerate non-overlapping upstream changes.

Test a patch before relying on it:

```bash
git -C ~/.config/quickshell/end4-pC apply --3way --check ~/end4-patches/my-feature.patch
```
