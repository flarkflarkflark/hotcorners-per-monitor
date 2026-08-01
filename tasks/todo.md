# Roadmap Checklist

## Planning gate

- [x] Confirm product intent and compatibility floor.
- [x] Map the current codebase and local Plasma environment.
- [x] Verify published KDE APIs/KCM conventions and identify undocumented timer risk.
- [x] Record architecture, normative schema, specification and impact analysis.
- [x] Run adversarial Codex review and reconcile all 21 findings.
- [ ] Human approves defaults, stay-zone, context inheritance, command-helper design and hard platform gates.

## v0.2.0

- [x] Add Python/JavaScript test harness and v0.1 fixtures.
- [x] Add normative v0.2 schema, zero-cooldown v0.1 migration and cross-language fixtures.
- [x] Add invalid/stale configuration protection and unknown-field preservation.
- [x] Add per-binding cooldown with fake-clock tests.
- [ ] Add specified session-D-Bus command runner without implicit shell.
- [ ] Install/remove the helper and D-Bus metadata through an ownership manifest.
- [ ] Add command/cooldown PyQt controls and fix installed gettext lookup.
- [ ] Add French translation.
- [ ] Add Spanish translation.
- [ ] Add Italian translation.
- [ ] Translate desktop entry and KWin package metadata; generalize translation install/removal.
- [ ] Test ambiguous/overlapping output ownership and malformed configuration.
- [ ] Run upgrade, fresh-install, interrupted-upgrade, uninstall, Wayland and X11 gates.
- [ ] Update docs/metadata/changelog and prepare v0.2.0 tag.

## v0.3.0

- [ ] Prove timer and per-output desktop APIs on Plasma 6.4/current, Wayland/X11.
- [ ] Add the normative tap/linger state machine and output ownership behavior.
- [ ] Add v0.3 context schema and lossless v0.2 migration.
- [ ] Add per-binding context fallback and per-output desktop resolution.
- [ ] Add GUI activity/desktop discovery.
- [ ] Add context selector and inheritance UI.
- [ ] Add tap/linger editor UI and translations.
- [ ] Run timing/context/rename/removal/hot-unplug and dual-monitor gates.
- [ ] Pass X11 gate; do not release while required platform support is pending.
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
