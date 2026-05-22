# Hot Corners Per Monitor

A KWin script for KDE Plasma 6 that brings **per-monitor hot corner and screen-edge configuration** — solving a long-standing pain point in multi-monitor setups where the standard KDE "Screen Edges" only allow global configuration, causing the inner corners (where two monitors meet) to fire actions you never wanted.

![Status](https://img.shields.io/badge/Plasma-6-blueviolet)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

## Why?

KDE's built-in *Screen Edges* settings apply to **all** monitors at once. With two or more displays side-by-side, the inner corners of each screen sit roughly in the middle of your workspace, where you can hit them accidentally dozens of times per day. The only fix has been to disable hot corners entirely — losing the feature on the outer corners where it would actually be useful.

This project gives every corner and edge of every connected monitor its own independent action, configured through a friendly GUI.

## Features

- **Visual monitor layout** — see your actual screen arrangement at scale and click directly on the corner or edge you want to configure. Configured handles are highlighted so you see your setup at a glance.
- **8 hot zones per monitor** (4 corners + 4 edge midpoints), configured independently.
- **Monitor identification by output name** (e.g. `DP-1`, `HDMI-A-1`) — stable across reboots and cable swaps.
- **Action types:** none, or invoke any KDE global shortcut (`Overview`, `Grid View`, `Show Desktop`, lock screen, application launcher, or any custom shortcut name).
- **Scales gracefully** from one monitor to many. Tested with up to six displays in mixed arrangements (side-by-side, stacked, ultrawide+laptop).
- **Multilingual** — English, Dutch (Nederlands), German (Deutsch). More translations welcome.
- **Pure standards compliance** — config is stored in `kwinrc` and applied via KWin's standard reconfigure mechanism.

## Requirements

- KDE Plasma 6 (tested on 6.4+)
- KWin 6 (Wayland or X11)
- `python3` and `python-pyqt6` (for the configuration GUI)
- `kwriteconfig6`, `kreadconfig6`, `qdbus6` (shipped with Plasma 6)

## Installation

One command:

```bash
./setup.sh
```

That runs an interactive setup that:

- Checks dependencies (and gives distro-specific install hints if any are missing)
- Installs the KWin script to `~/.local/share/kwin/scripts/hotcorners-per-monitor/`
- Installs the configuration GUI to `~/.local/share/hotcorners-per-monitor/` with a launcher at `~/.local/bin/hotcorners-config`
- Installs the desktop entry to `~/.local/share/applications/`
- Compiles & installs translation `.mo` files to `~/.local/share/locale/{nl,de}/LC_MESSAGES/`
- **Enables the KWin script** in `kwinrc` (no need to flip the switch in System Settings)
- **Offers to disable the built-in KDE hot corners** that would otherwise double-fire (with a backup saved to `~/.config/hotcorners-per-monitor-backup-electric-borders.conf` for restoration)
- Reloads KWin so changes take effect immediately
- Optionally launches the GUI when done

Flags:

```bash
./setup.sh --yes              # non-interactive, accept all defaults
./setup.sh --no-launch        # don't launch the GUI at the end
./setup.sh --keep-defaults    # don't touch the built-in hot corners
./setup.sh --disable-defaults # disable them without asking
./setup.sh --help             # show all options
```

To uninstall everything:

```bash
./uninstall.sh
```

## Usage

1. Launch **Hot Corners Per Monitor** from your application menu (or run `hotcorners-config`).
2. The window shows all your connected monitors at scale, with eight clickable handles per monitor (four corners + four edge midpoints).
3. Click a handle to select that corner/edge. The editor below shows the current action.
4. Pick an action from the dropdown — or choose "Custom shortcut" to type a `kglobalaccel` component and shortcut name directly.
5. Click **Apply**. KWin reloads instantly; your changes are live.

Configured handles fill in with the accent colour so you can see your active setup at a glance. The handles at the inner edges (where two monitors touch) are easy to spot and easy to leave unconfigured — solving the original multi-monitor frustration.

### Important: built-in hot corners

This script registers screen edges *in addition to* KDE's built-in hot corners — it does not replace them. To avoid double-triggering, the built-ins must be disabled.

`setup.sh` offers to do this automatically (with a backup file so you can restore them later). If you ran setup with `--keep-defaults`, you can disable them later in *System Settings → Screen Edges* (set every corner to "No Action"), or by running:

```bash
for corner in TopLeft TopRight BottomLeft BottomRight Top Bottom Left Right; do
    kwriteconfig6 --file kwinrc --group ElectricBorders --key $corner None
done
qdbus6 org.kde.KWin /KWin reconfigure
```

## Architecture

```
┌─────────────────────────────┐         ┌─────────────────────────┐
│ Configuration GUI (PyQt6)   │ writes  │ ~/.config/kwinrc        │
│ hotcorners_config.py        ├────────►│ [Script-hotcorners-…]   │
│                             │ kwrite- │ MonitorConfigs={…JSON…} │
│                             │ config6 │                         │
└─────────────────────────────┘         └────────────┬────────────┘
                                                     │ reads via
                                                     │ readConfig()
                                                     ▼
                                        ┌─────────────────────────┐
                                        │ KWin script (JS)        │
                                        │ main.js                 │
                                        │  • parses JSON          │
                                        │  • registers 8 edges    │
                                        │  • matches cursor to    │
                                        │    output by name       │
                                        │  • invokes shortcut via │
                                        │    callDBus()           │
                                        └─────────────────────────┘
```

The configuration is a single JSON-encoded string stored under the standard KWin script config group. This keeps everything within KDE's existing config infrastructure — no extra dotfiles, no custom daemons.

## Configuration schema

```json
{
  "DP-1": {
    "TopLeft":  { "type": "shortcut", "component": "kwin", "name": "Overview" },
    "TopRight": { "type": "none" }
  },
  "HDMI-A-1": {
    "TopRight":    { "type": "shortcut", "component": "kwin", "name": "Grid View" },
    "BottomRight": { "type": "shortcut", "component": "ksmserver", "name": "Lock Session" }
  }
}
```

Keys are output names as reported by KWin's `screen.name` (matches the connector name on Wayland and the XRandr output name on X11). Position IDs are `TopLeft`, `Top`, `TopRight`, `Right`, `BottomRight`, `Bottom`, `BottomLeft`, `Left`. Omitted positions default to no action.

## Translating

Translations live in `config-gui/translations/<locale>/LC_MESSAGES/hotcorners-config.po`. To add a new language:

```bash
cd config-gui
msginit --locale=fr_FR.UTF-8 -i translations/hotcorners-config.pot \
        -o translations/fr/LC_MESSAGES/hotcorners-config.po
# edit translations/fr/LC_MESSAGES/hotcorners-config.po with Lokalize or any editor
msgfmt translations/fr/LC_MESSAGES/hotcorners-config.po \
       -o translations/fr/LC_MESSAGES/hotcorners-config.mo
```

Pull requests with translations are very welcome.

## Roadmap

### v0.3 (current)
- Visual monitor arrangement canvas with click-to-configure handles
- All 8 hot zones per monitor (4 corners + 4 edge midpoints), monitor matching by output name
- Action types: none, invoke shortcut (built-in catalogue + custom)
- Translations: English, Dutch, German

### v0.4 (next)
- Direct command execution as an action type (in addition to shortcuts)
- "Tap vs linger" — short touch does action A, holding for N ms does action B
- Cooldown per corner to prevent rapid double-fires
- French, Spanish, Italian translations

### v0.5
- Native KCM (System Settings module) replacing the standalone PyQt6 GUI
- Per-activity configuration
- Per-virtual-desktop configuration

### Long-term
- Propose for inclusion in `plasma-workspace` as the new default Screen Edges KCM behaviour

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

## Acknowledgements

- The KDE community for the excellent KWin scripting API
- Filed under: things that should have been in KDE since the first multi-monitor user
