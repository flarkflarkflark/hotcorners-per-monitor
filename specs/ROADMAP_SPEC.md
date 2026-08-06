# Specification: Hot Corners Per Monitor v0.2.0–v0.4.0+

## Objective

Build the complete public roadmap as a sequence of independently releasable versions, then provide a native but externally installed KDE System Settings module. The external KCM must coexist with Plasma's existing Screen Edges module and serve as a technically credible prototype for possible later upstream adoption.

Primary users are Plasma 6.4+ users who need different hot-corner and edge behavior per output, activity and virtual desktop.

## Confirmed Scope

### v0.2.0

Product decision (2026-08-05): v0.2.0 absorbs what this document originally
scoped as a separate v0.3.0 (tap/linger and contexts), because both were
implemented and merged together before the original v0.2.0 gates/tag were
completed. French, Spanish and Italian translations are explicitly deferred
out of v0.2.0 — see "Deferred" below; they remain planned, not dropped.

- Add a `command` action containing one executable and an argument list.
- Never invoke an implicit shell; shell behavior requires an explicit executable such as `sh` with `-c` in its arguments.
- Add a configurable cooldown to each monitor-position binding to suppress rapid repeated activation.
- Preserve existing v0.1 shortcut configurations through automatic migration/normalization.
- Add tap-versus-linger bindings: leaving before a configurable threshold runs the tap action; remaining until the threshold runs the linger action.
- Preserve immediate execution for bindings that have no linger action.
- Add default, per-activity, per-virtual-desktop and combined activity-plus-desktop contexts.
- Resolve contexts by stable activity and virtual-desktop IDs, while displaying human-readable names.
- Context precedence: activity+desktop, activity, desktop, default.

#### Deferred (not v0.2.0 scope)

- Complete French, Spanish and Italian translations, including desktop metadata.
- GUI activity/desktop discovery (activities/desktops are entered as free text in v0.2.0).

### v0.4.0+

- Add a separately installable native KF6 KCM named **Hot Corners Per Monitor** beside Plasma's existing **Screen Edges** page.
- Use a C++ plugin with a Kirigami/QML UI and KDE's supported KCM packaging conventions.
- Keep `kwinrc` as the shared source of truth and retain compatibility with configurations written by the PyQt6 GUI.
- Provide safe install/uninstall/package workflows without replacing distribution-owned files.
- Compare the design with Plasma's existing Screen Edges KCM before fixing the native model/UI architecture, then document an upstream adaptation path. Upstream acceptance is not a deliverable.
- Give the KCM its own component lifecycle so KCM-only removal leaves the backend and user configuration intact.

## Explicit Non-Goals

- Plasma 5 support.
- Overwriting or hiding Plasma's existing Screen Edges KCM.
- Implicit shell parsing, command interpolation or privileged command execution.
- Guaranteeing acceptance into KDE upstream.
- Replacing KWin's built-in activation-delay, edge-barrier or tiling behavior.

## Behavioral Contract

`specs/CONFIG_SCHEMA.md` is normative for the complete document shape, actions, migrations, context inheritance, validation, output ownership, cooldown identity and tap/linger state machine.

Key decisions:

- New bindings default to a proposed 350 ms cooldown; migrated v0.1 bindings receive 0 ms to preserve behavior.
- New linger bindings default to a proposed 500 ms threshold and proposed 8-logical-pixel stay zone.
- `contexts.default` is the only fallback context. Explicit `none` blocks fallback; omission inherits from the same output and position.
- Desktop context is resolved for the output that activated the edge, not simply the active output.
- Overlapping/cloned output geometries are ambiguous and fail closed.
- Tap/linger dispatches at most one eligible action; cooldown or invalid/no-action values may produce zero.
- KWin's own activation delay occurs before tap/linger and remains controlled by Plasma.

### Command runner boundary

KWin JavaScript has no process API. v0.2 therefore adds a session-D-Bus-activated PyQt6 helper using the already required PyQt6 QtDBus and QtCore modules.

Normative interface:

```text
bus:       org.flark.HotCorners.CommandRunner
object:    /CommandRunner
interface: org.flark.HotCorners.CommandRunner1
method:    Run(string program, string argumentsJson) -> [bool accepted, string errorName]
wire:      in "ss", out "av" (QVariantList: accepted, then errorName)
```

The reply is a two-element `QVariantList`, which introspects as `av` rather
than a `(bs)` struct. Callers must therefore tolerate the values arriving
variant-wrapped, and must not assume a fixed-arity struct.

- `argumentsJson` must decode to at most 128 string arguments, each at most 16 KiB and at most 128 KiB total.
- `program` is non-empty, contains no NUL, and is at most 4096 bytes. Absolute paths are used directly; bare names are resolved using the helper's `PATH`.
- Working directory is the user's home directory. Environment is inherited from the D-Bus-activated graphical session.
- Launch uses `QProcess.startDetached(program, arguments, home)` without a shell.
- `accepted` means process creation was accepted, not that the process completed successfully. Validation and launch failures return a stable non-secret error name; command arguments are never logged.
- The service exits after 30 seconds idle and may be activated again by D-Bus.
- Session bus scope is transport, not authorization: any same-user process can call it, but that user can already execute processes. The helper never elevates privileges.
- The KWin callback logs only the error name when activation or launch fails.
- KWin's `callDBus()` is always asynchronous: it returns nothing and passes the reply values to an optional callback supplied as its last argument. The runtime must therefore collect the outcome in that callback. Treating the return value as the reply reports every call — including successful ones — as `invalid-helper-response`.

## Configuration Compatibility

- Every persisted document contains `schemaVersion` after a successful v0.2 save.
- Readers normalize older v0.1 data in memory; migrated bindings use zero cooldown.
- Writers emit only the current schema and preserve unknown fields within supported versions.
- Each schema transition has cross-language fixture tests.
- Invalid roots and unsupported versions run no actions and open read-only; Apply cannot overwrite the original.
- Invalid child bindings fail independently while valid siblings remain available.
- Writers detect raw-value changes since load and block stale Apply operations rather than silently overwriting another frontend's work.

## Supported Environment

- KDE Plasma/KWin 6.4 and newer.
- Wayland and X11.
- One or more outputs, including adjacent and scaled outputs.
- Current development host: Plasma/KWin 6.7.3, Wayland, two side-by-side 3440×1440 outputs at 125% scale.

## Commands

`tests/run-tests.sh` runs the current Python and JavaScript suites (228 Python tests passed, 2 skipped; 192 JavaScript tests, as of this writing). The CMake/CTest commands below apply from v0.4 onward, once the `kcm/` scaffold exists:

```bash
./tests/run-tests.sh                 # all Python and JavaScript tests
python3 -m unittest discover -s tests/python -v
node --test tests/js/*.test.js
python3 -m compileall -q config-gui command-runner
cmake -S kcm -B build/kcm -G Ninja  # from v0.4 onward
cmake --build build/kcm
ctest --test-dir build/kcm --output-on-failure
```

Manual runtime checks use `journalctl --user`/the KWin journal, `kcmshell6`, `qdbus6` and the two-monitor host.

## Project Structure

```text
kwin-script/                 KWin runtime backend
config-gui/                  PyQt6 configurator (v0.1–v0.3 compatibility UI)
command-runner/              Session-D-Bus process helper and activation metadata introduced in v0.2
tests/python/                schema, GUI-model and command-runner tests
tests/js/                    KWin backend tests with mocked KWin globals
kcm/                         native C++/QML KCM introduced in v0.4
specs/                       architecture, impact and roadmap documents
tasks/                       implementation plan and checklist
```

## Code Style

Match existing style and keep runtime logic in small testable functions. Example action dispatch shape:

```javascript
function executeAction(action) {
    if (!action || action.type === "none") return;
    // Validate the selected action type, then dispatch one side effect.
}
```

No framework, abstraction or dependency is added before a roadmap requirement needs it.

## Testing Strategy

- Pure schema, precedence, cooldown and tap/linger logic: small deterministic unit tests.
- KWin integration: execute `main.js` in Node's VM with mocked KWin globals, workspace, D-Bus and timers.
- Command helper: unit-test validation and integration-test the D-Bus method with a harmless temporary executable.
- PyQt UI: offscreen tests for action serialization and field visibility; manual visual verification remains required.
- Native KCM: Qt Test/model tests, CMake/CTest, `kcmshell6` smoke test and manual System Settings verification.
- Release gate: full suite, install into a disposable user prefix, dual-monitor Wayland checks and successful X11 verification. A release does not claim Wayland/X11 support while either required platform remains unverified.
- Plasma 6.4 timer and desktop-per-output APIs are proved in a focused spike before v0.3 implementation; source presence in 6.7 alone is insufficient.

## Boundaries

### Always

- Add a failing test before behavioral implementation.
- Keep old configuration fixtures and migration tests.
- Fail closed on malformed actions/configuration.
- Run focused tests after each slice and the full suite before release.
- Keep Plasma-owned files untouched.
- Block Apply when configuration is malformed, unsupported or stale.
- Install and remove files through component manifests; preserve pre-existing unrelated files.
- Reload the Hot Corners KWin script after every successful GUI or KCM
  Apply, using a mechanism proven live to actually reload it (a plain KWin
  reconfigure was proven not to; see `tasks/todo.md`).

### Ask first

- Add runtime dependencies beyond Qt/KF6/Python/PyQt6 already implied by the roadmap.
- Change the compatibility floor.
- Change context precedence, cooldown defaults or tap/linger semantics.
- Remove the PyQt6 compatibility UI.

### Never

- Run command actions through an implicit shell.
- Request privilege elevation.
- Delete unknown context configuration automatically.
- Disable tests to pass a release gate.
- claim upstream acceptance before KDE accepts a merge request.

## Success Criteria

- Each version is independently installable, removable, documented and tagged.
- v0.1 configuration loads unchanged after upgrading and receives zero cooldown.
- Cooldown suppresses duplicate dispatch independently for each resolved activation key.
- Commands preserve argument boundaries and cannot gain shell interpretation unless the configured program explicitly is a shell.
- Tap and linger dispatch at most one eligible action per activation cycle.
- Per-binding activity/desktop override precedence is deterministic and covered by tests.
- Ambiguous output ownership and malformed configuration fail closed without destroying the stored value.
- The KCM appears as a separate System Settings page, supports Apply/Reset/Defaults, reloads KWin and does not overwrite Plasma files.
- KCM-only removal leaves the backend and user configuration intact.
- The full automated suite and required manual gates pass on Wayland and X11 before release.

## Open Review Points

- Confirm or adjust the proposed 350 ms cooldown default.
- Confirm or adjust the proposed 500 ms linger default.
- Confirm the context precedence and per-binding inheritance rules.
- Confirm or adjust the proposed 8-logical-pixel linger stay zone.
- Plasma 6.4 Wayland and X11 test environments are established and have recorded QTimer-capability and tap/linger-timing gate results (`specs/spikes/results/`); the proposed defaults below were implemented against them but have not received the explicit human sign-off this section still requires.
