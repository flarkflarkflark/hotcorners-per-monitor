# Project Context

## Stack

- KDE Plasma/KWin 6.4+; current development host runs Plasma and KWin 6.7.3 on Wayland.
- KWin JavaScript script (`kwin-script/contents/code/main.js`) registers eight electric borders and dispatches configured actions.
- Python 3 + PyQt6 configuration application (`config-gui/hotcorners_config.py`).
- KConfig/`kwinrc` persistence through `kreadconfig6` and `kwriteconfig6`.
- D-Bus integration through `qdbus6` and KWin's script-level `callDBus()`.
- gettext `.po`/`.mo` translations.
- Shell installation and removal scripts.
- Planned native integration: C++20, Qt 6, KF6 KCMUtils, Kirigami/QML, ECM and CMake/Ninja.

## Architecture

Current data flow:

1. The PyQt6 GUI detects outputs through `QGuiApplication.screens()`.
2. It reads and writes one JSON value, `MonitorConfigs`, in `[Script-hotcorners-per-monitor]` in `kwinrc`.
3. A KWin reconfigure reloads the JavaScript backend.
4. The backend registers all eight global electric borders, identifies the output under the pointer, looks up the output/position action and invokes a KDE global shortcut over D-Bus.

Planned data flow:

- v0.2 adds a versioned configuration schema, per-binding cooldown state and a session-D-Bus-activated command runner. Commands are executable-plus-argument-list values and never implicitly evaluated by a shell.
- v0.3 resolves activity plus the virtual desktop for the output that owns the activation, then applies per-binding context fallback. A Plasma 6.4 compatibility spike must prove the timer primitive before tap-versus-linger implementation.
- v0.4 first compares the design with Plasma's current Screen Edges implementation, then adds a separately installable native KCM beside it. `kwinrc` remains the source of truth, with stale-write detection between frontends.

## Conventions Observed

- Python uses snake_case functions, type hints on selected public values and direct PyQt widget composition.
- JavaScript uses camelCase functions, `const`/`let`, early returns and plain JSON objects.
- Shell scripts use `set -euo pipefail` and user-local installation paths.
- Failures are currently logged or converted to safe empty/default configuration values.
- User-visible strings use gettext in the PyQt application.

## Signals / Active Considerations

- There are currently no automated tests; every behavioral change is high-risk until a harness exists.
- `MonitorConfigs` is a shared interface between the GUI and KWin script and needs explicit schema migrations.
- The published KWin scripting API exposes `registerScreenEdge()`, `callDBus()`, activity/desktop access and cursor signals, but the edge callback carries no output argument.
- KWin 6.7 source exposes a constructible JavaScript `QTimer`; the published API does not guarantee it, so Plasma 6.4 must be proved experimentally.
- KWin scripts do not expose `QProcess`; direct execution therefore needs the specified session-local D-Bus helper boundary.
- Plasma 6.4 is the compatibility floor, while the development host is newer (6.7.3); tests must avoid relying only on 6.7 APIs.
- The local manual test topology is two 3440×1440 DisplayPort outputs (`DP-2`, `DP-1`) at 125% scale, arranged side-by-side on Wayland.
- X11 behavior requires an additional test environment because the current host session is Wayland; X11 is a hard release gate.
- Connector names are not stable monitor identities across cable/dock changes. v0.2/v0.3 retain them for compatibility, preserve orphaned entries and correct the documentation; v0.4 decides reassignment before fixing the native model.
