# Codex Adversarial Review — Roadmap Planning

Date: 2026-08-01
Tool: Codex CLI 0.144.5, read-only sandbox
Scope: roadmap/spec/impact/architecture/tasks against the current implementation

The built-in fresh reviewer failed to launch (`spawn pi ENOENT`). The user explicitly authorized a Codex CLI cross-model review. Codex returned 21 findings. The parent reconciled each finding against the artifacts as follows.

| # | Severity | Classification | Disposition |
|---|---|---|---|
| 1 | Blocker | Valid + actionable | Added normative v2/v3 document shapes, validation and migrations in `CONFIG_SCHEMA.md`. |
| 2 | Blocker | Valid + actionable | Defined per-binding fallback; explicit `none` blocks fallback and omission inherits. |
| 3 | Blocker | Valid + actionable | Defined exactly-one geometry ownership; overlap/clone/no-match fails closed; added boundary/hot-unplug tests. |
| 4 | Blocker | Valid + actionable | Corrected timer claim: present in 6.7 source but undocumented; added mandatory Plasma 6.4/current API spike. |
| 5 | Blocker | Valid + actionable | Defined logical-pixel zone, proposed tolerance, threshold tie, re-entry, repeated callback, context change, hot-unplug and reconfigure rules. |
| 6 | Blocker | Valid + actionable | Made X11 a hard release gate for every supported release; removed “pending” escape. |
| 7 | High | Valid + actionable | Require desktop resolution for the activated output, subject to the Plasma 6.4 API spike. |
| 8 | High | Valid + actionable | Defined root versus child validation, unknown-version handling and unknown-field behavior. |
| 9 | High | Valid + actionable | Unsupported/malformed roots open read-only; Apply cannot replace original raw data. |
| 10 | High | Valid + actionable | Writers keep a raw digest, reread before Apply and block stale writes rather than merging silently. |
| 11 | High | Valid + actionable | Specified bus/object/interface/method, limits, lookup, cwd, environment, lifetime and errors. Clarified session bus is not authorization. |
| 12 | High | Valid + actionable | Added helper/D-Bus metadata install, activation and manifest-based removal to v0.2 task/gate. |
| 13 | High | Valid + actionable | Added installed gettext-domain lookup fix and installed-locale tests to v0.2. |
| 14 | High | Valid + actionable | Translation task now includes KWin package `Name`/`Description` metadata. |
| 15 | High | Valid + actionable | Added separate KCM component install/KCM-only uninstall lifecycle; full-product uninstall remains separate. |
| 16 | High | Valid + actionable | KCM Apply must reconfigure KWin and has an integration test. |
| 17 | High | Valid + actionable | Moved Screen Edges source/behavior delta analysis before native KCM architecture. |
| 18 | Medium | Valid trade-off resolved | Migrated v0.1 bindings use 0 ms to preserve behavior; new bindings use proposed 350 ms. |
| 19 | Medium | Valid + actionable | Reworded invariant to “at most one eligible action”; cooldown/none/failure may produce zero. |
| 20 | Medium | Valid trade-off documented | Connector names retained through v0.3 for compatibility, orphaned entries preserved, stability claim corrected; reassignment decided before v0.4 model. |
| 21 | Medium | Valid + actionable | Added component ownership manifests, collision preservation, interrupted-upgrade and stale-file tests. |

## Stop condition

One adversarial cycle completed. Every finding is dispositioned; no finding was dismissed as noise. Remaining choices are explicitly listed in the human review gate rather than silently selected for implementation.
