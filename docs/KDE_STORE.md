# Installing from the KDE Store

This document explains what the KDE Store ("Get New Scripts" / Discover) package
actually installs, why it behaves differently from the full GitHub installer, and
how to get a working setup from it.

## What the Store package is

The KDE Store distributes exactly one thing for a KWin script: the KWin/Script
KPackage itself (the contents of this repository's `kwin-script/` directory,
built by `tools/build-kde-store-package.sh`). KDE's package-fetching mechanism
(`kpackagetool6`, used internally by both Discover and the "Get New Scripts"
button in System Settings → Window Management → KWin Scripts) copies that
package into `~/.local/share/kwin/scripts/hotcorners-per-monitor/` and nothing
else.

**It cannot run a shell script as part of installation.** This is a KDE/KNewStuff
platform constraint, not a limitation specific to this project — there is no
supported hook for a KWin script to run arbitrary setup code when installed
through the Store. Practically, this means the Store package does **not**
include and cannot install:

- The configuration GUI (`config-gui/hotcorners_config.py` and its launcher)
- The command-runner D-Bus helper (`command-runner/command_runner.py`) that
  "run a command" actions depend on
- A desktop entry, translations, or an installed application icon

## What works with the Store package alone

- The KWin script loads and registers all 8 hot-zone edges per monitor.
- **Shortcut actions** work fully: the script invokes `kglobalaccel` directly
  (`org.kde.kglobalaccel` over D-Bus), with no dependency on the command-runner
  helper.
- Cooldown, tap/linger, and per-activity/per-desktop context overrides all work,
  since that logic lives entirely in `main.js`.

## What does not work, and why

**Command actions silently fail.** A binding of `{"type": "command", ...}` asks
the script to invoke `org.flark.HotCorners.CommandRunner` over D-Bus. Without
the full installer, that service was never registered — no shell fallback is
used (the whole point of the D-Bus helper is to avoid ever building a shell
command line from user input), so the action simply does not run. Nothing
crashes; the corner just does nothing.

**There is no Configure button in System Settings.** Configuring hot zones
means editing the `MonitorConfigs` JSON document (see the schema below) — the
KWin script has no `contents/ui/config.ui`, so KWin's script list shows no
"Configure…" affordance for it.

## Getting a fully working install

If you want the configuration GUI and command actions, use the full installer
instead of (or in addition to) the Store package:

```bash
git clone https://github.com/flarkflarkflark/hotcorners-per-monitor
cd hotcorners-per-monitor
./setup.sh
```

`setup.sh` installs everything the Store package cannot: the GUI, its launcher,
the desktop entry, translations, the icon, and the command-runner D-Bus
service. If you already installed from the Store, running `setup.sh`
afterwards is safe — it upgrades the same KWin script in place via
`kpackagetool6` and adds the missing pieces alongside it.

## Enabling the script after a Store install

KWin scripts are never auto-enabled, from the Store or otherwise:

1. System Settings → Window Management → KWin Scripts
2. Find **Hot Corners Per Monitor**, tick its checkbox
3. Apply

## Power-user path: editing the configuration by hand (not recommended)

Without the GUI, the only way to configure hot zones from a Store-only install
is to edit `kwinrc` directly:

```ini
[Script-hotcorners-per-monitor]
MonitorConfigs={"DP-1":{"TopLeft":{"type":"shortcut","component":"kwin","name":"Overview"}}}
```

The value is the same JSON document the GUI writes — see [`specs/CONFIG_SCHEMA.md`](../specs/CONFIG_SCHEMA.md)
for the full schema, and the main [README](../README.md#configuration-schema) for
a quick example. After editing, reload the script (System Settings → Window
Management → KWin Scripts → toggle it off and on, or log out and back in) for
the change to take effect.

This path is **not recommended**: there is no validation, a malformed JSON
document is silently ignored rather than reported, output names must be typed
exactly as KWin reports them, and command actions still won't work (see
above). Use `setup.sh` and the GUI if at all possible.
