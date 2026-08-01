# Impact Analysis: Full Roadmap

## Target

The shared `MonitorConfigs` contract and every component that reads, writes, installs, removes or documents it.

## Dependents (9)

- `kwin-script/contents/code/main.js`: parses configuration, resolves output/position and dispatches actions.
- `kwin-script/contents/config/main.xml`: declares the KWin script configuration key.
- `kwin-script/metadata.json`: package metadata and release version.
- `config-gui/hotcorners_config.py`: reads/writes the contract and edits actions.
- `config-gui/translations/*`: translates every user-visible configuration field.
- `config-gui/hotcorners-config.desktop`: exposes localized application metadata.
- `setup.sh`: installs backend, GUI and translations and enables the script.
- `uninstall.sh`: removes installed components and configuration.
- `README.md`: documents actions, schema, dependencies, installation and releases.

New dependents will include the D-Bus command helper and native KCM.

## Affected Roadmap Stories

- v0.2 command actions modify dispatch, persistence, GUI, installation and security boundaries.
- v0.2 cooldown modifies runtime state and each binding's schema/UI.
- v0.2 translations expand all message catalogs and installation/removal loops.
- v0.3 tap/linger changes activation timing and binding shape.
- v0.3 activities/desktops introduce context selection, stable identifiers and override precedence.
- v0.4 native KCM adds a second writer for the same contract and a C++/QML build/package system.

## Test Coverage

- Current automated coverage: none.
- Gap: configuration parsing and migration.
- Gap: output/position lookup and action dispatch.
- Gap: D-Bus shortcut and command calls.
- Gap: cooldown and timer state.
- Gap: context precedence.
- Gap: PyQt action-editor serialization.
- Gap: setup/uninstall ownership, D-Bus helper activation and independent KCM lifecycle.
- Gap: malformed/stale whole-document writes and installed gettext lookup.
- Gap: Wayland/X11, ambiguous output ownership, hot-unplug and multi-output desktop behavior.

## Risk: High

The central unversioned JSON value is a shared public interface, there are no automated tests, and the roadmap adds timing, process execution, context resolution and a second whole-document writer. The edge callback has no output argument, timer support is undocumented at the compatibility floor and the current host cannot verify X11.

## Recommended Action

1. Add a test harness and legacy configuration fixtures before changing behavior.
2. Implement the normative `CONFIG_SCHEMA.md` contract with tested migrations, invalid-data preservation and stale-write detection.
3. Deliver one release at a time, using separate short-lived branches and tags.
4. Implement and installation-test the exact D-Bus command-helper contract.
5. Prove timer/per-output desktop APIs on Plasma 6.4 and current Plasma before v0.3 behavior work.
6. Require Wayland and X11 before each supported release.
7. Compare current Screen Edges behavior/source before fixing the native v0.4 architecture.
8. Keep the existing Screen Edges KCM untouched and give the external KCM an independent lifecycle.
