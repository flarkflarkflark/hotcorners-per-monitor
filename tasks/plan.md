# Implementation Plan: Hot Corners Per Monitor Roadmap

## Overview

Deliver v0.2.0, v0.3.0 and the external native v0.4.0 KCM as separate releases. Each release begins from the previous tagged release, uses short-lived feature branches and preserves a working install. The highest risks—configuration compatibility, command execution and linger timing—are tested before broad UI work.

**Status update (2026-08-05):** Phase 1 and Phase 2 below were both implemented before either was tagged and released. By product decision, they now ship together as a single v0.2.0 — see `CHANGELOG.md` and `tasks/todo.md` for current release status. The task breakdown and checkpoints below are kept as-written because they accurately describe how the work was actually built and tested, task by task; only the release/tag boundary changed, not the implementation sequence.

## Architecture Decisions

- `kwinrc` remains the source of truth across both configuration frontends.
- `specs/CONFIG_SCHEMA.md` is the normative shared contract for Python, JavaScript and C++.
- Commands cross the specified session-D-Bus boundary as program plus JSON-encoded argument list; no implicit shell exists.
- KWin remains responsible for edge detection; output ownership requires exactly one geometry match and otherwise fails closed.
- Context override precedence is activity+desktop → activity → desktop → default, resolved independently per output/position binding.
- Writers preserve malformed/unsupported input, detect stale whole-document writes and block Apply instead of silently overwriting.
- The native KCM is additive, separately installable/removable and does not replace Plasma's Screen Edges files.

## Official KDE Basis

- KWin's published scripting API exposes `registerScreenEdge()`, `unregisterScreenEdge()`, `callDBus()`, activity/desktop properties and cursor signals: https://develop.kde.org/docs/plasma/kwin/api/
- KWin 6.7 source exposes a JavaScript `QTimer`, but this is not guaranteed by the published API; Plasma 6.4 behavior must be proved before v0.3 implementation: https://invent.kde.org/plasma/kwin/-/blob/Plasma/6.7/src/scripting/scripting.cpp
- KDE KCMs are dynamically loaded plugins with C++ and QML, installed as KPackages: https://develop.kde.org/docs/features/configuration/kcm/
- `KQuickConfigModule` documents the plugin/QML package contract: https://api.kde.org/kquickconfigmodule.html
- Managed KConfig integration should expose a parent-owned config object rather than a singleton: https://develop.kde.org/docs/features/configuration/kconfig_xt/
- Plasma Screen Edges source is analyzed before v0.4 architecture and reused for later upstream adaptation: https://invent.kde.org/plasma/kwin/-/tree/Plasma/6.7/src/kcms/screenedges

## Phase 1: v0.2.0 Foundation

### Task 1: Establish deterministic test commands

**Acceptance criteria**
- Python unittest and Node built-in test entry points run from one repository script.
- Legacy v0.1 configuration and action fixtures exist.
- Current shortcut dispatch behavior is covered before production changes.

**Verification**
- `./tests/run-tests.sh`

**Dependencies:** None
**Likely files:** `tests/run-tests.sh`, `tests/fixtures/v0.1-config.json`, `tests/js/backend.test.js`, `tests/python/test_config.py`
**Scope:** Medium

### Task 2: Version and normalize the v0.2 schema

**Acceptance criteria**
- v0.1 maps normalize to the exact v2 contract without action loss and with zero cooldown.
- Newly created v0.2 bindings default to the approved cooldown.
- Invalid roots open read-only and cannot be overwritten; invalid child bindings fail independently.
- Unknown fields are preserved and stale raw-value changes block Apply.
- Schema fixtures round-trip in Python and JavaScript.

**Verification**
- Focused Python and JavaScript schema tests; full test script.

**Dependencies:** Task 1
**Likely files:** `config-gui/config_schema.py`, `kwin-script/contents/code/main.js`, `tests/python/test_config_schema.py`, `tests/js/backend.test.js`
**Scope:** Medium

### Task 3: Implement per-binding cooldown

**Acceptance criteria**
- Duplicate activation inside the configured cooldown does not dispatch.
- Different output/position/context keys do not block one another.
- Zero cooldown preserves immediate repeated dispatch.

**Verification**
- Node tests with a fake clock; manual repeated-edge test on `DP-1` and `DP-2`.

**Dependencies:** Task 2
**Likely files:** `kwin-script/contents/code/main.js`, `tests/js/backend.test.js`, `config-gui/hotcorners_config.py`, `tests/python/test_action_editor.py`
**Scope:** Medium

### Task 4: Implement the command-runner boundary

**Acceptance criteria**
- The helper implements the exact bus/object/interface/method, validation limits, lookup, environment, working-directory, idle-lifetime and error contract in the specification.
- It launches through `QProcess.startDetached()` without shell parsing and rejects malformed requests without logging arguments.
- The KWin backend dispatches command actions and handles activation/launch failure safely.
- Setup installs the helper and D-Bus activation metadata; uninstall removes only files recorded in the component manifest.

**Verification**
- Unit tests plus a harmless integration executable that records exact argv.
- Confirm pipes/redirections remain literal arguments unless `sh -c` is explicitly configured.
- Fresh install, D-Bus activation and uninstall integration test.

**Dependencies:** Task 2
**Likely files:** `command-runner/hotcorners_command_runner.py`, D-Bus activation metadata, `kwin-script/contents/code/main.js`, `setup.sh`, `uninstall.sh`, focused tests (split implementation and packaging if over five files)
**Scope:** Medium

### Task 5: Add v0.2 GUI controls

**Acceptance criteria**
- Action type offers none, shortcut and command.
- Command UI edits program and ordered arguments without a shell command field.
- Cooldown is editable per selected binding and persists through Apply/Reload.
- Malformed, unsupported or stale configuration disables Apply and remains unmodified.
- Installed gettext lookup selects the application domain in the user locale directory instead of stopping at an unrelated system directory.

**Verification**
- Offscreen PyQt tests and manual configuration on both outputs.

**Dependencies:** Tasks 2–4
**Likely files:** `config-gui/hotcorners_config.py`, `config-gui/config_schema.py`, `tests/python/test_action_editor.py`
**Scope:** Medium

### Task 6: Add French, Spanish and Italian

**Acceptance criteria**
- Every POT message has a reviewed translation in `fr`, `es` and `it`.
- Desktop entry plus KWin package `Name` and `Description` metadata are translated.
- Setup and uninstall process all shipped locales generically.
- Installed-locale tests prove the GUI does not silently fall back to English.

**Verification**
- `msgfmt --check` for every catalog; launch under each locale.

**Dependencies:** Task 5
**Likely files:** three new `.po` catalogs, `config-gui/hotcorners-config.desktop`, `setup.sh`, `uninstall.sh`
**Scope:** Medium (split by locale if needed)

### Checkpoint: v0.2.0 release

- Full tests and syntax checks pass.
- Fresh user-local install and uninstall succeed.
- Upgrade from a real v0.1 configuration preserves shortcuts.
- Commands and cooldown pass dual-monitor Wayland and X11 manual tests.
- Malformed/stale configuration and ambiguous/overlapping output cases fail closed.
- Installer manifest preserves pre-existing unrelated files and supports safe interrupted-upgrade cleanup.
- README corrects connector-name stability claims; metadata and changelog reflect v0.2.0; release is tagged separately.

## Phase 2: v0.3.0 Context and Timing

### Task 7: Prove Plasma 6.4 timing and per-output desktop APIs

**Acceptance criteria**
- A disposable KWin script proves or disproves constructible timer behavior on Plasma 6.4 and current Plasma.
- The exact API for obtaining the current desktop of the activated output is proved on both versions.
- If either API is unavailable, implementation stops for a revised design instead of using an undocumented fallback silently.

**Verification**
- Recorded journal output and minimal script fixtures from Plasma 6.4 and 6.7+ Wayland/X11 sessions.

**Dependencies:** v0.2.0 tag
**Likely files:** `spikes/kwin-api-probe/`, `specs/tech-architecture/tech-stack.md`
**Scope:** Small

### Task 8: Add the normative tap/linger state machine

**Acceptance criteria**
- No-linger bindings preserve immediate behavior.
- The approved logical-pixel zone, threshold tie, re-entry, repeated callback, context change, hot-unplug and reconfigure rules match `CONFIG_SCHEMA.md`.
- At most one eligible action dispatches; cooldown may suppress it.
- Output ownership requires exactly one geometry match; overlaps/clones fail closed.

**Verification**
- Fake timer, cursor, screen topology and configuration-generation tests; real KWin timing test on Wayland and X11.

**Dependencies:** Task 7
**Likely files:** `kwin-script/contents/code/main.js`, `tests/js/backend.test.js`, `tests/js/tap-linger.test.js`
**Scope:** Medium

### Task 9: Introduce v0.3 contexts and migrations

**Acceptance criteria**
- Schema implements the exact default/activity/desktop/combined contract.
- v0.2 data migrates into default without loss and preserves cooldown.
- Resolution falls back independently per output/position; explicit `none` blocks fallback.
- Desktop context is selected for the activated output, not the active output.
- Unavailable contexts remain stored and invalid children do not invalidate valid siblings.

**Verification**
- Cross-language migration, precedence, explicit-none and multi-output desktop suites.

**Dependencies:** Task 8
**Likely files:** `config-gui/config_schema.py`, `kwin-script/contents/code/main.js`, `tests/python/test_config_schema.py`, `tests/js/context_resolution.test.js`
**Scope:** Medium

### Task 10: Add activity and desktop discovery to the GUI

**Acceptance criteria**
- Activities and virtual desktops are listed with stable IDs and names.
- Missing saved contexts remain visible as unavailable and are not deleted.
- Connector-based output identity is labelled honestly and disconnected output entries remain recoverable.

**Verification**
- Parser tests against D-Bus fixtures and manual checks against the local Default activity/four desktops.

**Dependencies:** Task 9
**Likely files:** `config-gui/context_provider.py`, `config-gui/hotcorners_config.py`, `tests/python/test_context_provider.py`
**Scope:** Medium

### Task 11: Add v0.3 context and tap/linger UI

**Acceptance criteria**
- User can select default or an override context and edit monitor bindings there.
- User can configure tap action, optional linger action and threshold.
- UI distinguishes inherited, explicit action and explicit `none` states.
- Stale-write detection remains active across long-running editor sessions.

**Verification**
- Offscreen UI tests and manual four-desktop/dual-monitor flow.

**Dependencies:** Tasks 9–10
**Likely files:** `config-gui/hotcorners_config.py`, `config-gui/config_schema.py`, `tests/python/test_action_editor.py`, translation template/catalogs
**Scope:** Large; implement as separate context-selector and binding-editor slices.

### Checkpoint: v0.3.0 release

- v0.2 migration is proven.
- Timing, output ownership and context suites pass.
- Tap/linger and per-output override precedence pass real Wayland and X11 tests.
- Activity/desktop rename/removal and screen hot-unplug cases are manually checked.
- Documentation, translations, package metadata and tag are complete.

## Phase 3: v0.4.0 Native External KCM

### Task 12: Analyze upstream Screen Edges before native design

**Acceptance criteria**
- A delta report compares data model, lifecycle, layout, accessibility, maximize/tile/barrier/delay controls and packaging with current `kcm_kwinscreenedges`.
- The proposed external model identifies reusable seams and avoids choices that would prevent preserving built-in behavior in a future replacement.
- Output identity/fingerprint and manual reassignment options are decided before the C++ model is fixed.

**Verification**
- Review against Plasma 6.4 and current KWin source; architecture decision recorded before Task 13.

**Dependencies:** v0.3.0 tag
**Likely files:** `specs/UPSTREAM_DELTA.md`, architecture decision record
**Scope:** Medium

### Task 13: Build an isolated KCM scaffold spike

**Acceptance criteria**
- CMake finds Qt6, ECM, KF6 KCMUtils and Kirigami at the Plasma 6.4 floor.
- A minimal external `kcm_hotcorners_per_monitor` opens with `kcmshell6`.
- Metadata places it beside, not over, Screen Edges.

**Verification**
- Configure/build/install into a disposable prefix; run with generated `prefix.sh` on Plasma 6.4 and current Plasma.

**Dependencies:** Task 12
**Likely files:** `kcm/CMakeLists.txt`, `kcm/src/CMakeLists.txt`, `kcm/src/kcm.cpp`, `kcm/src/kcm.json`, `kcm/package/contents/ui/main.qml`
**Scope:** Medium

### Task 14: Implement a tested native configuration model

**Acceptance criteria**
- C++ model reads/writes/migrates the same normative schema as v0.3.
- Apply, Reset and Defaults obey KCM semantics; successful Apply reconfigures KWin.
- Invalid/unsupported/stale values block Apply and preserve the original.
- Python and C++ fixture results match.

**Verification**
- Qt Test/CTest contract tests using shared JSON fixtures and a KWin reconfigure integration test.

**Dependencies:** Task 13
**Likely files:** C++ config model, KCM class, CMake, Qt tests, shared fixtures
**Scope:** Large; split model, migration and KCM lifecycle into separate slices.

### Task 15: Port the monitor/context/binding UI to Kirigami

**Acceptance criteria**
- Native UI exposes every v0.3 capability and the approved output reassignment behavior.
- Monitor geometry and configured handles remain understandable at common scales.
- Keyboard navigation, labels and accessible names cover all controls.

**Verification**
- QML tests where practical, `kcmshell6` smoke test and manual System Settings review at 125% scale.

**Dependencies:** Task 14
**Likely files:** focused QML components under `kcm/package/contents/ui/`, KCM model bindings, tests
**Scope:** Large; split canvas, context selector and binding editor.

### Task 16: Package independent KCM lifecycle and coexistence

**Acceptance criteria**
- External KCM installs without writing distribution-owned files and records an ownership manifest.
- Existing PyQt-written configuration opens unchanged.
- A KCM-only uninstall target removes only KCM-owned files and leaves configuration, command runner and KWin script intact.
- Full-product uninstall remains explicit and preserves unrelated/pre-existing files.

**Verification**
- Disposable-prefix and user-local install, upgrade, interrupted-install and KCM-only/full uninstall smoke matrix.

**Dependencies:** Tasks 14–15
**Likely files:** top-level/KCM CMake, component install scripts/manifests, packaging docs and smoke tests
**Scope:** Medium

### Checkpoint: v0.4.0 release

- CMake build and CTest pass.
- KCM appears as a separate System Settings page; Apply/Reset/Defaults and immediate KWin reload work.
- KCM-only removal leaves runtime and user configuration intact.
- All v0.3 configurations and runtime behavior remain compatible.
- Plasma 6.4 and current Plasma pass Wayland and X11 gates.
- The upstream delta report shows how existing Screen Edges capabilities remain preservable.

## Phase 4: Upstream Adaptation (post-v0.4)

### Task 17: Engage KDE and adapt the prototype

- Present the external prototype and pre-v0.4 delta report to KDE maintainers.
- Revise architecture based on maintainer feedback before invasive upstream changes.
- Split reusable runtime/configuration pieces from project-specific packaging.
- Preserve existing maximize/tile/barrier/delay settings in any replacement proposal.
- Treat upstream review and acceptance as external outcomes, not release criteria.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| No current tests | High | Harness and legacy fixtures are Task 1. |
| KWin has no process API | High | Normative D-Bus helper contract; no shell; exact-argv and install tests. |
| Tap/linger relies on undocumented timing support | High | Plasma 6.4/current API spike before implementation; stop on failure. |
| Edge callback has no output argument | High | Exactly-one geometry ownership rule and ambiguity/hot-unplug tests. |
| Two config UIs lose updates | High | Raw digest check; stale Apply blocked; no silent merge. |
| Plasma 6.4 API differs from 6.7 host | High | Dedicated 6.4 gates before v0.3 and v0.4 implementation. |
| Existing Screen Edges double-fires | Medium | Keep current warning and installation conflict handling. |
| X11 unavailable on current session | High | Required VM/secondary X11 session; release blocks if unverified. |
| Connector names are not hardware identity | Medium | Honest docs now; retain orphans; decide reassignment before native model. |
| Upstream direction differs | Medium | Analyze source before v0.4 design; engage maintainers after prototype. |

## Human Review Gate

Approve or revise `specs/ROADMAP_SPEC.md`, especially:

1. 350 ms default cooldown for new bindings; migrated v0.1 bindings use 0 ms.
2. 500 ms default linger threshold.
3. 8 logical px linger stay-zone tolerance.
4. Per-binding context precedence/inheritance rules.
5. The fully specified session-D-Bus command-helper boundary.
6. X11 and Plasma 6.4 are hard release gates, not optional status notes.

Implementation starts only after this plan is approved.
