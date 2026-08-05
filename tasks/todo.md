# Roadmap Checklist

## Planning gate

- [x] Confirm product intent and compatibility floor.
- [x] Map the current codebase and local Plasma environment.
- [x] Verify published KDE APIs/KCM conventions and identify undocumented timer risk.
- [x] Record architecture, normative schema, specification and impact analysis.
- [x] Run adversarial Codex review and reconcile all 21 findings.
- [ ] Human approves defaults, stay-zone, context inheritance, command-helper design and hard platform gates.
- [x] Document v3 default-context fallback semantics and examples.

## v0.2.0

Product decision (2026-08-05): the next public release is v0.2.0, and its
scope is the implementation currently on `main` — command actions, cooldown,
tap/linger, and contexts/fallback all ship together as v0.2.0. This folds in
everything that was previously checklisted as a separate "v0.3.0" (tap/linger,
contexts, their editor UI) since it was already built and merged (see
`feature/v0.2-roadmap-foundation`, PR #1) before the old v0.2.0 checkpoint's
gates and tag were completed. French/Spanish/Italian translations and GUI
Activity/Desktop discovery are explicitly out of v0.2.0 scope — see
"Future work" below; they are deferred, not dropped.

- [x] Add Python/JavaScript test harness and v0.1 fixtures.
- [x] Add normative v0.2 schema, zero-cooldown v0.1 migration and cross-language fixtures.
- [x] Add invalid/stale configuration protection and unknown-field preservation.
- [x] Normalize v0.1/v0.2 configuration in the KWin runtime.
- [x] Add per-binding cooldown with fake-clock tests.
- [x] Complete Plasma 6.4 Wayland/X11 QTimer capability gates (6.7 Wayland smoke passes).
- [x] Apply timer-backed cooldown gating in KWin runtime.
- [x] Add specified session-D-Bus command runner without implicit shell.
- [x] Add no-shell command helper client contract in KWin runtime.
- [x] Install/remove the helper and D-Bus metadata through an ownership manifest.
- [x] Add command/cooldown PyQt controls and fix installed gettext lookup.
- [x] Add the normative tap/linger state machine and output ownership behavior.
- [x] Add context schema (default/activity/desktop/combined) and lossless v0.2 migration.
- [x] Add per-binding context fallback and per-output desktop resolution.
- [x] Add context selector and inheritance UI.
- [x] Add tap/linger editor UI.
- [x] Test ambiguous/overlapping output ownership and malformed configuration.
- [x] Generalize `uninstall.sh` translation-catalog removal to match `setup.sh`'s generic install loop, so any future locale is cleaned up on uninstall instead of only a hardcoded `nl`/`de`.
- [x] Atomically stage and validate installed GUI/desktop-entry/launcher files before replacing a live install (command-runner helper already did this; KWin package install already had its own fixed/tested contract).
- [x] Run upgrade and fresh-install gates on live Plasma/KWin 6.7.3 Wayland (see incident/rollback/re-attempt history on the kpackagetool6 destructive-upgrade branch).
- [x] Update docs/metadata for v0.2.0 (this document, README.md, specs/ROADMAP_SPEC.md, kwin-script/metadata.json, draft release notes).
- [x] Fix the runtime context resolution to actually walk the documented
      activity+desktop -> activity -> desktop -> default cascade instead of
      resolving only the single most-specific key (20 new JS tests).
- [x] Fix command-runner D-Bus reply parsing so array/variant-wrapped genuine
      successes are no longer misreported as `invalid-helper-response`.
- [x] Distinguish save failure causes (stale write, missing tool, write
      command failure, invalid document) instead of one generic message; add
      a further distinct `ReloadFailedError` so a failed/absent post-write
      `qdbus6 reconfigure` is reported honestly instead of the GUI claiming
      "your changes are active now" when that was never confirmed.
- [x] Add an explicit, confirmed v2 -> v3 upgrade action in the GUI (legacy
      documents no longer require hand-editing JSON to reach tap/linger and
      contexts).
- [x] Add GUI activity/desktop discovery via `org.kde.ActivityManager` and
      KWin's `VirtualDesktopManager` D-Bus interfaces (PyQt6.QtDBus, no new
      dependency); stale saved identifiers are shown as unavailable and kept,
      not silently dropped; "Refresh list" re-queries both.
- [x] Add tooltips and an in-app Help dialog covering hot zones, actions
      (including the no-shell command guarantee), cooldown, tap/linger, and
      the context fallback order; German and Dutch translations complete.
- [ ] **Open, blocking, no workaround invented:** determine whether
      `qdbus6 org.kde.KWin /KWin reconfigure` (the mechanism `save_config()`
      currently calls, and that README.md/tech-stack.md currently describe
      as reloading "the JavaScript backend") actually reloads a running KWin
      script's *code* (re-running `loadConfig()` in
      `kwin-script/contents/code/main.js`, which is otherwise only called
      once at script bootstrap and is wired to no reconfigure signal), or
      only reloads generic workspace/window-manager settings. This project's
      own `specs/spikes/QTIMER_SPIKE.md` already proved a different, working
      mechanism for forcibly reloading this exact script's code —
      `org.kde.kwin.Scripting.unloadScript`/`loadScript` by package id
      (`hotcorners-per-monitor`) — but only for an ephemeral probe script
      installed under a throwaway package id, not for reloading the
      persistently-installed, currently-running production script. Needs a
      dedicated live spike (same rigor as `QTIMER_SPIKE.md`) on the required
      Plasma/KWin 6.4 gates before either keeping `reconfigure` or switching
      `save_config()`'s reload step to the Scripting interface. Do not tag
      `v0.2.0` claiming reliable "changes are active now" behavior until
      this is resolved.
- [ ] Prove timer and per-output desktop APIs on Plasma 6.4/current, Wayland/X11. (QTimer capability is proven on Plasma 6.4 Wayland and X11, see `specs/spikes/QTIMER_SPIKE.md` and `specs/spikes/results/`; the per-output desktop API (`currentDesktopForScreen`) is implemented and unit-tested but has no dedicated Plasma 6.4 spike record.)
- [ ] Run the physical AMD smoke checklist for the full v0.2.0 feature set (see the release-candidate gate plan) — not yet executed.
- [ ] Run interrupted-upgrade, uninstall, and X11 gates for the full v0.2.0 feature set (commands, cooldown, tap/linger, contexts) — Wayland-only so far.
- [ ] Run context/activity rename-removal and hot-unplug gates. (Wired in the runtime — `screensChanged` cleanup, unavailable-context preservation — but no recorded manual gate.)
- [ ] Pass X11 gate for the full v0.2.0 feature set; do not release while required platform support is pending. (Tap/linger timing alone has an X11 pass at Plasma 6.4; commands and contexts have not had a dedicated X11 gate run.)
- [ ] Prepare and create the `v0.2.0` tag, and publish the release, once the gates above pass.

## Future work (post-v0.2.0)

Deferred out of v0.2.0 scope by product decision (2026-08-05). Still valid,
not dropped.

- [ ] Add French translation.
- [ ] Add Spanish translation.
- [ ] Add Italian translation.
- [ ] Translate desktop entry and KWin package metadata for fr/es/it.

## v0.4.0

- [ ] Compare current Screen Edges source/behavior before fixing KCM architecture.
- [ ] Decide output fingerprint/manual reassignment policy.
- [ ] Scaffold external KF6/Kirigami KCM in a disposable prefix.
- [ ] Add native schema/configuration model and cross-language contract tests.
- [ ] Implement Apply/Reset/Defaults, stale-write protection and immediate KWin reload.
- [ ] Port monitor canvas to accessible Kirigami/QML.
- [ ] Port context selector and binding editor.
- [ ] Add independent KCM install/KCM-only uninstall lifecycle and manifests.
- [ ] Test against Plasma 6.4 and current Plasma.
- [ ] Pass Wayland and X11 gates.
- [ ] Update docs/metadata/changelog and prepare v0.4.0 tag.

## Post-v0.4 upstream preparation

- [ ] Preserve existing Screen Edges tiling/barrier/delay capabilities in proposal.
- [ ] Present the pre-v0.4 KDE-facing design/delta document.
- [ ] Ask KDE maintainers for architectural feedback.
- [ ] Adapt into upstream-sized merge requests only after feedback.
