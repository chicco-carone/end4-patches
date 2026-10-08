# end4-pC Local Patches

This folder contains optional local changes for `~/.config/quickshell/end4-pC`.

| Feature | Patch |
| --- | --- |
| Display refresh mode button | `display-mode.patch` |
| NetworkManager VPN button | `vpn-toggle.patch` |
| ModemManager LTE/cellular signal indicator | `lte-signal.patch` |
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
`~/.local/bin` and enables the `end4-display-mode.service` and
`end4-display-mode.socket` systemd user units automatically. Reapplying the patch
upgrades the old button in place. The button connects directly to the socket,
without relying on `PATH`. Set `END4_BIN_DIR` to use another helper installation
directory. Selecting the peripheral
battery and G84 toggle patches likewise installs `epomaker-battery` and
`g84-profile.py`; the peripheral patch still expects `mow` in `PATH`.
Each patch is standalone and can be installed or removed independently.

The LTE patch adds cellular signal bars beside the Wi-Fi/Ethernet icon whenever
ModemManager detects a modem. It requires `mmcli` (ModemManager) in `PATH`, with
no helper script or extra service. It reads cached modem status every 10 seconds
and hides the icon when no modem is found. Hover for the operator, radio technology,
connection state, and signal percentage. Disabled or locked modems show an off
icon; unregistered modems or unavailable signal readings show a no-data icon.
If several modems are present, a connected modem takes priority, followed by a
registered modem. This also works with cellular technologies other than LTE.

```bash
~/end4-patches/patches.sh apply lte-signal
```

The display worker requires Python 3 and Monique profiles named `Builtin` (120 Hz)
and `Builtin 60hz`. It starts at user login, waits for Hyprland, and checks AC
power every two seconds: AUTO uses 120 Hz on AC and 60 Hz on battery. Manual
selections override AC changes. Only the worker calls Monique; the button sends
`auto`, `120hz`, or `60hz` through `$XDG_RUNTIME_DIR/end4-display-mode.sock`.
The selected mode survives worker restarts and logins in
`~/.local/state/end4/display-mode` (or under `XDG_STATE_HOME`). The bar sends its
saved selection when it starts. Failed profile changes retry automatically, and
systemd restarts the worker after a crash. Removing the patch disables and removes
both units.

```bash
ac-power-profile --set-mode auto
systemctl --user status end4-display-mode.service end4-display-mode.socket
journalctl --user -u end4-display-mode.service -b
```

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
