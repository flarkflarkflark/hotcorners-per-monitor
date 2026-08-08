# Roadmap Checklist

## Planning gate

- [x] Confirm product intent and compatibility floor.
- [x] Map the current codebase and local Plasma environment.
- [x] Verify published KDE APIs/KCM conventions and identify undocumented timer risk.
- [x] Record architecture, normative schema, specification and impact analysis.
- [x] Run adversarial Codex review and reconcile all 21 findings.
- [x] Human approves defaults, stay-zone, context inheritance, command-helper design and hard platform gates. Explicit sign-off recorded 2026-08-07: default cooldown 350 ms — YES; default linger threshold 500 ms — YES; stay-zone radius 8 px — YES; context precedence (activity+desktop → activity → desktop → default) — YES; explicit None blocks fallback — YES; command execution remains direct/no implicit shell — YES.
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
      a further distinct `ReloadFailedError` so a failed/absent script
      reload is reported honestly instead of the GUI claiming "your changes
      are active now" when that was never confirmed.
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
- [x] Determine and implement the reliable KWin script reload mechanism.
      Live spike on this project's AMD Plasma/KWin 6.7.3 Wayland host
      proved `qdbus6 org.kde.KWin /KWin reconfigure` reloads neither the
      script's code nor `MonitorConfigs`, and proved
      `org.kde.kwin.Scripting.unloadScript` -> `loadScript` -> `Script.run()`
      reliably reloads both for the persistently-installed production
      script (not just the ephemeral probe `QTIMER_SPIKE.md` used),
      repeated three times live with no duplicated `/Scripting` objects and
      no `kwin_wayland` restart. `config-gui/hotcorners_config.py`'s
      `save_config()`, `setup.sh`, and `uninstall.sh` all now use this
      sequence, with focused deterministic tests (fake qdbus6 binaries, no
      live D-Bus in automated tests).
- [x] Live-retest the *implementation* of the proven reload mechanism found
      a real gap: a config change needed a second Apply before it took
      effect. Root cause, proven live (not guessed): `reconfigure` is
      NoReply/fire-and-forget and does not itself make a freshly reloaded
      script's `readConfig()` see a value just written -- KWin's shared
      kwinrc cache is only reparsed some time after the D-Bus call returns,
      with no completion signal available (confirmed with `dbus-monitor`
      across a 2s window). 0.1s was not enough; 0.2s/0.3s were, repeatably.
      Also separately confirmed the physical retest had initially run a
      stale installed GUI copy predating the reload-mechanism fix -- the
      launcher runs the installed copy in `~/.local/share/hotcorners-per-monitor/`,
      not the checkout; see the guard test below.
- [x] Add the settle wait: `KWIN_RECONFIGURE_SETTLE_SECONDS` (0.5s, GUI) /
      `HCPM_RECONFIGURE_SETTLE_SECONDS` (0.5s, `setup.sh`) between
      `reconfigure` and the script reload sequence. Documented as a
      conservative compatibility interval with a safety margin over the
      observed minimum, not a formal KWin completion guarantee. Added a
      guard test asserting the installed `hotcorners_config.py` matches the
      repository source byte-for-byte after `setup.sh`, so a stale install
      cannot silently reproduce an already-fixed bug again.
- [x] Live-retest of the settle-wait fix confirmed the application itself,
      including single-Apply behavior, now works correctly. It found one
      separate remaining bug: launching from the Plasma application menu
      failed with "Could not find the program 'hotcorners-config'", because
      the installed desktop entry's `Exec` line was the bare command name
      and a graphical Plasma session does not necessarily inherit
      `~/.local/bin` in `PATH`, even though the same command works from a
      shell.
- [x] Fix the application-menu launcher: `setup.sh` now substitutes the
      desktop entry's `Exec` line with the absolute installed launcher path
      (quoted/escaped per the Desktop Entry Specification when needed)
      instead of shipping a hardcoded or bare command; the repository
      template stays a portable bare `Exec=hotcorners-config`. Reinstalling
      also repairs a stale entry from before this fix.
- [x] Live-retest the application-menu launcher fix: `./setup.sh --yes`,
      confirm `~/.local/share/applications/hotcorners-config.desktop`'s
      `Exec` line is the absolute `~/.local/bin/hotcorners-config` path,
      run `kbuildsycoca6`, launch from the Plasma application menu, and
      confirm the shell command `hotcorners-config` still works too. See
      the exact checklist in the launcher-fix commit's final report.
      Confirmed live on the primary AMD Plasma/KWin 6.7.3 Wayland host: the
      application-menu launcher and the direct shell launch both work, and
      the desktop entry uses the absolute installed launcher path.
- [ ] Prove timer and per-output desktop APIs on Plasma 6.4/current, Wayland/X11. (QTimer capability is proven on Plasma 6.4 Wayland and X11, see `specs/spikes/QTIMER_SPIKE.md` and `specs/spikes/results/`; the per-output desktop API (`currentDesktopForScreen`) is implemented and unit-tested but has no dedicated Plasma 6.4 spike record.)
- [x] Run the physical AMD smoke checklist for the full v0.2.0 feature set on
      Wayland (see the release-candidate gate plan). Completed 2026-08-06 on
      the primary AMD Plasma/KWin 6.7.3 Wayland host (hybrid live-system
      methodology: automated where safe, one manual physical action at a
      time otherwise). Sections A–J all PASS, or PASS with a documented,
      non-blocking limitation:
      per-monitor ownership including the shared inner boundary between the
      two monitors; single-Apply activation; cooldown (suppression,
      post-cooldown retrigger, 0 ms, default 350 ms feel); tap vs. linger
      (tap, linger, stay-zone cancel, default threshold/stay-zone feel,
      cooldown interaction); command actions (exactly-once execution,
      byte-exact argument preservation, live shell-metacharacter-injection
      attempt proven inert, correct D-Bus `av` wire format, correct distinct
      error names for malformed input); all four context-precedence levels
      (combined, activity-only, desktop-only, default) and explicit-`None`-
      blocks-fallback physically confirmed across the host's real four
      virtual desktops, plus discovery names/IDs, stale-ID preservation and
      Refresh-without-data-loss in the GUI; v2→v3 upgrade (cancel path,
      accept path, preserved bindings/cooldowns, schemaVersion 3 on disk);
      save/reload failure-message classification (missing tool, write
      failure, reload failure, stale-write conflict all reproduced live with
      isolated fakebin `PATH` injection, never touching the real system
      tools); repeated-reload stability (3 cycles, script's own `/Scripting`
      object ID held constant, no duplicate triggers, `kwin_wayland` PID
      unchanged for the entire session); and the icon/launcher. Ambiguous-
      ownership fail-closed and malformed-context-entry fail-closed were not
      physically reproduced (no overlapping-output hardware available) and
      rely on the automated suite. One structural (non-code) finding: newly
      added `hicolor` icons don't appear in Kickoff/taskbar until the next
      `plasmashell` restart — confirmed correct via `kmenuedit` and file
      checksum instead; not a defect, out of scope to force-fix without
      restarting Plasma.
- [x] Pass the X11 gate for the full v0.2.0 feature set. Completed
      2026-08-07 on the primary AMD Plasma/KWin 6.7.4 X11 host, same hybrid
      live-system methodology as the Wayland pass. Sections A–H all PASS:
      per-monitor triggering (including the shared boundary, using this
      session's real XRandr output names `DisplayPort-0`/`DisplayPort-1`
      rather than Wayland's connector names `DP-2`/`DP-1` for the same
      hardware — expected, not a defect); single Apply; cooldown; tap/linger;
      command actions; all four context-precedence levels plus discovery on
      X11; v2→v3 upgrade; repeated-reload stability (script ID held
      constant, no duplicate triggers, `kwin_x11` PID unchanged for the
      entire session). Mid-gate finding: `MonitorCanvas._is_configured()`
      never recognized v3 `tap`/`linger` bindings, so v3 hot zones painted
      as unconfigured — fixed as a narrow, test-first commit (see below) and
      re-verified live before resuming.
- [x] Run interrupted-upgrade and uninstall gates for the full v0.2.0
      feature set. Completed 2026-08-07: interrupted-upgrade resilience
      verified end-to-end through 5 real `setup.sh` failure boundaries
      (before GUI replacement, mid-staged-GUI-install, before command-runner
      replacement, before desktop-entry/icon replacement, before KWin
      reload) in an isolated HOME, each confirming no half-written targets,
      the previously-working install left intact where atomicity promises
      that, and a clean full recovery on rerun. `uninstall.sh` run for real
      against the live X11 install: script unloaded immediately, all 9
      project-owned files removed, unrelated files/scripts/config
      untouched, matching documented policy; `setup.sh` reinstall achieved
      full recovery with working bindings.
- [x] Run context/activity rename-removal and hot-unplug gates. Completed
      2026-08-07 on the X11 host: a real virtual desktop was renamed (name
      updated everywhere including GUI discovery, ID stayed stable, its
      binding kept working), a temporary desktop was created, bound, and
      removed (the stale context entry survived and stayed visible in the
      GUI, fallback correctly produced no action rather than leaking the
      orphaned binding), and the sole activity was renamed and restored
      (discovery confirmed). Activity **removal** was intentionally not
      attempted — removing the only activity was judged not low-risk.
      Hot-unplug was run as a **software output disable/re-enable**
      substitute (explicitly accepted in place of a physical cable pull):
      KWin and the script stayed alive while the non-primary output was
      disabled, the remaining monitor's binding kept working, the disabled
      output's binding failed closed with no cross-contamination, config
      was preserved, GUI discovery correctly dropped then restored the
      output, and no duplicate outputs or script objects appeared across
      the cycle. A literal physical cable hot-unplug was not performed.
- [ ] Prepare and create the `v0.2.0` tag, and publish the release, now that the gates above pass.

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
