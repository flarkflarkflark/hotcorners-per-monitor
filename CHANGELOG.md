# Changelog

## v0.2.0 (release candidate — not yet tagged or released)

**Status: draft.** This entry describes the feature set on `main` as of the
`release/v0-next-readiness` branch. A physical retest on the primary AMD
Plasma/KWin 6.7.3 Wayland host confirmed the reload mechanism, single-Apply
activation, `setup.sh` install/reload, the application-menu launcher fix, and
existing shortcut bindings. The full v0.2.0 feature-set smoke checklist
(command actions, cooldown, tap/linger, context overrides) and the X11 gate
have **not** yet been run — do not read this entry as a claim that live
verification of the full feature set is complete. It will be updated with
real results before the `v0.2.0` tag is created.

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
- **Explicit v2 → v3 upgrade**: a legacy (schema version 2) configuration now
  offers an "Enable tap/linger and contexts…" action in the GUI, gated by
  confirmation, that migrates every existing action and cooldown into the
  new `Default` context unchanged. Cancelling leaves the document untouched;
  merely opening the GUI never upgrades anything.
- **Activity/desktop discovery**: the context editor now discovers current
  KDE activities and virtual desktops via `org.kde.ActivityManager` and
  KWin's `VirtualDesktopManager` D-Bus interfaces and lists them by name,
  instead of requiring a hand-typed internal identifier. A saved identifier
  that no longer resolves is shown as "unavailable" and kept, not silently
  dropped, and a "Refresh list" action re-queries both sources.
- **Contextual help**: tooltips on every non-obvious control (action type,
  shortcut fields, command program/arguments, cooldown, tap/linger, context
  editing) and a Help dialog explaining hot zones, actions, cooldown,
  tap/linger, and the context fallback order. German and Dutch translations
  are complete.

### Fixed

- **Context precedence cascade**: the runtime now actually walks the
  documented `activity+desktop → activity → desktop → default` fallback
  order. Previously it resolved only a single most-specific key, so an
  activity-only or desktop-only override could never match while both an
  activity and a desktop were active — the normal case, not an edge case.
  Reproduced live on Plasma/KWin 6.7.3 Wayland before the fix.
- **Command-runner D-Bus response parsing**: a genuine success reply
  delivered as a bare array or a variant-wrapped value is now correctly
  recognized, instead of being misreported as `invalid-helper-response`.
- **Save failure classification**: stale-write conflicts, a missing
  `kreadconfig6`/`kwriteconfig6`, a failing write command, and an
  unnormalizable document now each produce their own actionable message,
  instead of one generic "check that kwriteconfig6 is available" message
  that misdescribed every cause as the others. A concurrent external edit
  reproduced live is no longer reported as a possibly missing tool.
- **Reliable KWin script reload**: proven live on Plasma/KWin 6.7.3 Wayland
  that `qdbus6 org.kde.KWin /KWin reconfigure` reloads neither this script's
  code nor `MonitorConfigs` — `main.js` only calls `loadConfig()` once, at
  bootstrap, with no reconfigure signal wired to re-run it. The GUI's Apply
  path, `setup.sh`, and `uninstall.sh` now use the sequence proven live to
  reliably reload both: `org.kde.kwin.Scripting.unloadScript` → `loadScript`
  → `Script.run()`, repeated three times live with no duplicated script
  objects and no `kwin_wayland` restart. A failed or missing reload step is
  no longer silently ignored: the GUI previously always reported
  "Configuration saved. KWin has been reloaded — your changes are active
  now," even when that reload step never ran. It now reports a distinct
  "Reload uncertain" outcome, and adopts the write's new baseline regardless
  so the next save is compared against what is actually on disk.
  `uninstall.sh` now unloads the running script before removing its files
  (best-effort — a D-Bus error is reported but never blocks cleanup),
  instead of relying on the same unproven `reconfigure` call.
- **Single-Apply activation**: a config change made through the GUI could
  require a second Apply before it took effect. `reconfigure` is
  NoReply/fire-and-forget — it returns before KWin has necessarily reparsed
  its shared, in-process kwinrc cache, and KWin exposes no completion
  signal for this (confirmed with `dbus-monitor` across a 2s window).
  Proven live: reloading the script immediately after `reconfigure` still
  read the *previous* `MonitorConfigs` generation, repeatably; 0.1s was not
  enough, 0.2s/0.3s were. The GUI's Apply path and `setup.sh` now wait a
  conservative, documented `KWIN_RECONFIGURE_SETTLE_SECONDS` (0.5s, a
  compatibility interval with a safety margin over the observed minimum —
  not a formal KWin completion guarantee) between `reconfigure` and the
  script reload sequence, so `readConfig()` sees the value just written on
  the first Apply.
- **Application-menu launcher**: launching "Hot Corners Per Monitor" from
  the Plasma application menu could fail with "Could not find the program
  'hotcorners-config'", even though running `hotcorners-config` from a
  shell worked. The installed desktop entry's `Exec` line was the bare
  command name, and a graphical Plasma session does not necessarily
  inherit `~/.local/bin` in its `PATH`. `setup.sh` now substitutes the
  `Exec` line with the absolute installed launcher path
  (`~/.local/bin/hotcorners-config`, quoted/escaped per the Desktop Entry
  Specification if the path needs it) instead of shipping it hardcoded in
  the repository template, which stays a portable bare command. Re-running
  `setup.sh` also repairs a previously-installed entry that still has the
  old bare `Exec=hotcorners-config` line. The shell command
  `hotcorners-config` is unaffected and still works for anyone with
  `~/.local/bin` in their shell `PATH`.
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
- The `unloadScript`/`loadScript`/`Script.run()` reload mechanism was proven
  live on Plasma/KWin 6.7.3 Wayland on this project's AMD development host:
  a plain `reconfigure` reloaded neither script code nor `MonitorConfigs`,
  and the reload sequence reliably reloads script *code*, repeated three
  times with no duplicated `/Scripting` script objects and no
  `kwin_wayland` restart. A follow-up physical retest then showed that code
  reload alone is not sufficient for the *config* to be observed on the
  first Apply: `reconfigure` asynchronously refreshes KWin's own
  configuration cache with no completion signal available, so a settle
  wait between `reconfigure` and the reload sequence is also currently
  required (see "Single-Apply activation" above). A follow-up physical
  retest confirmed the updated `setup.sh`/GUI code paths: a single Apply
  now activates a newly changed binding immediately, `setup.sh` installs
  and reloads successfully, the previously-existing shortcut bindings still
  work, and the application-menu launcher fix (absolute installed launcher
  path in the desktop entry) works alongside the direct shell launcher.
  `uninstall.sh` and the command/cooldown/tap-linger/context feature set
  have not yet had their own live retest — see `tasks/todo.md` for the
  exact outstanding checklist.

### Deferred to future work (not in v0.2.0)

- French, Spanish and Italian translations (including desktop entry and
  KWin package metadata).

## v0.1.0 (2026-05-22)

Initial public release.

- Visual monitor arrangement canvas with click-to-configure handles.
- All 8 hot zones per monitor (4 corners + 4 edge midpoints), matched by
  output name.
- Action types: none, or invoke a KDE global shortcut (built-in catalogue or
  custom).
- Translations: English, Dutch, German.
