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
- [ ] Add French translation.
- [ ] Add Spanish translation.
- [ ] Add Italian translation.
- [ ] Translate desktop entry and KWin package metadata for fr/es/it; generalize `uninstall.sh` translation removal to match `setup.sh`'s generic install loop (it currently only removes `nl`/`de`, see release-readiness audit).
- [x] Test ambiguous/overlapping output ownership and malformed configuration.
- [x] Run upgrade and fresh-install gates on live Plasma/KWin 6.7.3 Wayland (see incident/rollback/re-attempt history on the kpackagetool6 destructive-upgrade branch).
- [ ] Run interrupted-upgrade, uninstall, and X11 gates (Wayland-only so far; no X11 pass recorded for the current feature set).
- [ ] Update docs/metadata/changelog and prepare v0.2.0 tag.

## v0.3.0

Implementation of this section is substantially ahead of its checklist
position: the items below were built and merged (see `feature/v0.2-roadmap-foundation`,
PR #1) before the v0.2.0 checkpoint's gates and tag were completed. They are
implemented and unit/integration-tested; they are not yet covered by the
live/manual gates this checklist still requires, and no v0.3.0 release has
been tagged. See the release-readiness audit for the implementation-vs-release
distinction.

- [ ] Prove timer and per-output desktop APIs on Plasma 6.4/current, Wayland/X11. (QTimer capability is proven on Plasma 6.4 Wayland and X11, see `specs/spikes/QTIMER_SPIKE.md` and `specs/spikes/results/`; the per-output desktop API (`currentDesktopForScreen`) is implemented and unit-tested but has no dedicated Plasma 6.4 spike record.)
- [x] Add the normative tap/linger state machine and output ownership behavior.
- [x] Add v0.3 context schema and lossless v0.2 migration.
- [x] Add per-binding context fallback and per-output desktop resolution.
- [ ] Add GUI activity/desktop discovery. (Activity/desktop IDs are still entered as free text in the GUI; nothing queries KActivities or KWin for the available list.)
- [x] Add context selector and inheritance UI.
- [x] Add tap/linger editor UI.
- [ ] Run timing/context/rename/removal/hot-unplug and dual-monitor gates. (Tap/linger timing is gated on Plasma 6.4 Wayland and X11, deterministic and real; context/activity rename-removal and hot-unplug are wired in the runtime — `screensChanged` cleanup, unavailable-context preservation — but have no recorded manual gate.)
- [ ] Pass X11 gate; do not release while required platform support is pending. (Tap/linger timing has an X11 pass at Plasma 6.4; the full v0.3 feature set — contexts, command actions — has not had a dedicated X11 gate run.)
- [ ] Update docs/metadata/changelog and prepare v0.3.0 tag.

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
