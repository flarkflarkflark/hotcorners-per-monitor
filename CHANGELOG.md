# Changelog

## v0.2.0 (release candidate — not yet tagged or released)

**Status: draft.** This entry describes the feature set on `main` as of the
`release/v0-next-readiness` branch. The physical smoke checklist in
`specs/spikes/` / the release-candidate gate plan has not been run on this
system yet — do not read this entry as a claim that live AMD verification is
complete. It will be updated with real results before the `v0.2.0` tag is
created.

### Added

- **Command actions**: any corner/edge can run a program directly, in
  addition to invoking a KDE shortcut. Dispatched through a session-D-Bus
  helper (`org.flark.HotCorners.CommandRunner`) with no implicit shell —
  arguments are passed as an explicit argv list, never shell-interpolated.
- **Cooldown**: each binding can suppress rapid repeated activation with a
  configurable cooldown (0–10000 ms; new bindings default to 350 ms).
- **Tap vs. linger**: a short touch and a held touch (past a configurable
  threshold, default 500 ms, with an 8-logical-pixel stay zone) can now
  trigger different actions on the same corner/edge.
- **Contexts**: bindings can be overridden per activity, per virtual desktop,
  or per activity+desktop combination, with deterministic fallback to
  `contexts.default` when no override applies. Desktop context is resolved
  for the output that actually activated the edge.
- **Fail-closed output ownership**: if two or more monitor geometries both
  claim the cursor position (overlapping or cloned outputs), no action
  dispatches, instead of guessing which monitor was meant.
- Installed-GUI translation lookup now correctly finds the user-local
  catalog instead of silently stopping at an unrelated system locale
  directory that happens to exist but has no translation for this app.

### Fixed

- `setup.sh` no longer passes the live KWin script install directory as
  `kpackagetool6`'s upgrade source — doing so caused `--upgrade` to delete
  its own source before copying, silently leaving no KWin script installed
  while still reporting success. Upgrades now install from the repository
  source, verify the result independently, and abort loudly on any failure.
- `uninstall.sh` now removes every installed `hotcorners-config.mo`
  translation catalog it finds, instead of a hardcoded `nl`/`de` list, so
  future locales don't leave orphaned files behind on uninstall.
- `setup.sh` now stages the GUI script, its schema module, the desktop
  entry, and the generated launcher in place before an atomic rename,
  instead of copying/writing straight into the live destination — a failed
  or interrupted install can no longer leave a truncated file over a
  previously-working install.

### Upgrading from v0.1.0

- Existing v0.1 configuration (`kwinrc` → `[Script-hotcorners-per-monitor]`
  → `MonitorConfigs`) is read and normalized automatically on first load;
  no manual migration step is required.
- v0.1 bindings are migrated to schema version 2 with a `0` ms cooldown, so
  their observable trigger behavior is unchanged after upgrading. This was
  verified on a live two-monitor Plasma/KWin 6.7.3 Wayland host: both
  pre-existing `Overview` shortcut bindings were preserved exactly, and only
  the `MonitorConfigs` value itself changed in `kwinrc`.
- Configuration stays at schema version 2 (the flat, v0.1-compatible shape)
  until you actually use a v0.2.0-only feature such as an activity/desktop
  context override; only then does it move to schema version 3. Existing
  installs that never touch contexts are unaffected by the new schema.
- `setup.sh` can be re-run on an existing install to upgrade in place.

### Platform validation

- **Wayland**: validated on Plasma 6.4 (dedicated QTimer-capability and
  tap/linger-timing gates, see `specs/spikes/results/`) and on Plasma 6.7.3
  (live install/upgrade/dispatch smoke test on this project's AMD
  development host).
- **X11**: QTimer capability and tap/linger timing specifically have a
  recorded Plasma 6.4 X11 pass. Commands and context resolution have **not**
  yet had a dedicated X11 gate run — this is an open release-candidate item,
  not a completed one.
- No live verification yet exists for interrupted-upgrade recovery,
  uninstall, or hot-unplug/rename behavior with the current (command +
  cooldown + tap/linger + context) feature set on this host. See
  `tasks/todo.md` and the release-candidate gate plan for the exact
  outstanding checklist.

### Deferred to future work (not in v0.2.0)

- French, Spanish and Italian translations (including desktop entry and
  KWin package metadata).
- Automatic KDE Activity/Desktop discovery in the GUI (activity/desktop IDs
  are entered as free text for now).

## v0.1.0 (2026-05-22)

Initial public release.

- Visual monitor arrangement canvas with click-to-configure handles.
- All 8 hot zones per monitor (4 corners + 4 edge midpoints), matched by
  output name.
- Action types: none, or invoke a KDE global shortcut (built-in catalogue or
  custom).
- Translations: English, Dutch, German.
