# QTimer Capability Spike

## Conclusion: PARTIAL / BLOCKED

The isolated probe passes on the available Plasma/KWin 6.7.3 Wayland session.
This is supplementary smoke evidence only. Plasma/KWin 6.4 Wayland and X11
were not available and are both **NOT RUN**, so timer-backed production
cooldown is not approved.

## Question

Can a KWin script implement cooldown with one active one-shot `QTimer` per
`outputName + position`, rejecting events while active and releasing the key on
timeout, without an absolute monotonic JavaScript clock?

## Official source basis

| Source | Evidence used |
|---|---|
| [KWin Plasma/6.4 `scripting.cpp`, branch head `4018344761abe6b7c5fb7b1c22374799f769cae6`](https://invent.kde.org/plasma/kwin/-/blob/4018344761abe6b7c5fb7b1c22374799f769cae6/src/scripting/scripting.cpp) | KWin wraps `ScriptTimer::staticMetaObject` with `QJSEngine::newQMetaObject()` and installs it as global `QTimer`. |
| [KWin Plasma/6.4 `scripting.h`, same commit](https://invent.kde.org/plasma/kwin/-/blob/4018344761abe6b7c5fb7b1c22374799f769cae6/src/scripting/scripting.h) | `ScriptTimer` subclasses `QTimer`; its constructor is `Q_INVOKABLE`, making `new QTimer()` possible through the script engine. |
| [Official KWin scripting API](https://develop.kde.org/docs/plasma/kwin/api/) | Published KWin scripting surface; it does not document the timer capability, so source and runtime proof are required. |
| [Qt 6 QJSEngine](https://doc.qt.io/qt-6/qjsengine.html) | `newQMetaObject()` exposes `Q_INVOKABLE` constructors. QObject integration exposes QObject properties, methods, signals, and slots through the proxy object. |
| [Qt 6 QTimer](https://doc.qt.io/qt-6/qtimer.html) | `singleShot`, `timerType`, `interval`, `start()`, `stop()`, `active`, and `timeout`; starting an active timer stops and restarts it. |
| [Qt::TimerType](https://doc.qt.io/qt-6/qt.html#TimerType-enum) | `Qt::PreciseTimer` has numeric value `0`. |
| [QTimer accuracy](https://doc.qt.io/qt-6/qtimer.html#accuracy-and-timer-resolution) | Precise timers never time out earlier than requested. Any timer may time out late; an overrun emits `timeout()` only once. |

### Expected JavaScript shape

```javascript
const timer = new QTimer();
timer.singleShot = true;
timer.timerType = 0; // Official Qt::PreciseTimer enum value.
timer.interval = 350;
timer.timeout.connect(callback);
timer.start();
```

The local standalone KWin engine did not expose `Qt.PreciseTimer` through a
`Qt` global. The documented equivalent numeric value `0` was accepted, and all
50 configured timers read back `timerType === 0`. If that readback fails in any
required environment, the gate fails rather than falling back to the default
`Qt::CoarseTimer`.

Documentation establishes intended Qt semantics, but cannot prove that KWin's
JavaScript proxy exposes every needed property/signal correctly, that cleanup
destroys pending callbacks, or that Plasma 6.4 behaves identically on Wayland
and X11. Those require the probe.

## Probe

Location: `spikes/kwin-qtimer-probe/`

The probe:

- creates no screen edges and invokes no shortcuts;
- reads and writes no application or KWin configuration;
- imports no production code;
- logs stable `HCPM_QTIMER_PROBE` JSON markers;
- uses no `Date.now()` or `performance.now()`;
- is loaded ephemerally through `/Scripting.loadScript` and removed through
  `/Scripting.unloadScript`;
- measures durations externally using `journalctl --user -o short-monotonic`.

The verifier requires 20 unique start/timeout pairs for each interval, rejects
missing or duplicate callbacks, rejects any measured duration below the
requested interval, and reports callbacks more than five seconds late as a
stall signal.

## Local environment

| Field | Value |
|---|---|
| Distribution | EndeavourOS |
| Plasma | 6.7.3 |
| KWin | 6.7.3 |
| Qt | 6.11.1 |
| Session | Wayland (`XDG_SESSION_TYPE=wayland`) |
| Desktop | KDE |
| Compositor | `/usr/bin/kwin_wayland --xwayland` |
| Probe package id | `hotcorners-per-monitor-qtimer-probe` |

Commands:

```bash
spikes/kwin-qtimer-probe/run-local-smoke.sh /tmp/hcpm-qtimer-probe-local
python3 spikes/kwin-qtimer-probe/verify-log.py \
  --cleanup-confirmed /tmp/hcpm-qtimer-probe-local/journal.log
```

The runner used these KWin D-Bus operations internally:

```text
org.kde.kwin.Scripting.loadScript(sourcePath, packageId)
org.kde.kwin.Script.run()
org.kde.kwin.Scripting.unloadScript(packageId)
org.kde.kwin.Scripting.isScriptLoaded(packageId)
```

No package was persistently installed and `kwinrc` was not edited. Bounded
machine-readable evidence is retained in
`spikes/kwin-qtimer-probe/results/plasma-6.7.3-wayland/`; the raw journal was
removed after verification.

## Local runtime evidence

### Capability matrix

| Capability | Plasma 6.7.3 Wayland | Evidence |
|---|---|---|
| Constructor | PASS | `new QTimer()` completed; constructor marker emitted. |
| Timeout connection | PASS | All 40 measured timers invoked connected callbacks. |
| Single-shot | PASS | Readback was true; zero duplicate callbacks. |
| PreciseTimer/readback | PASS | All 50 timer configurations read back `timerType: 0`. |
| Stop/cancel | PASS | `stop()` produced `active: false`; observer saw timeout count 0. |
| Independent timers | PASS | Fictitious `DP-1:TopLeft` and `HDMI-A-1:TopRight` each timed out once. |
| Restart behavior | PASS | Restarting an active 350 ms timer reset its deadline; timeout occurred 350.860 ms after restart. |
| Interval zero semantics | PASS | A single-shot zero timer emitted exactly one callback. Production `cooldownMs: 0` must still bypass timer gating. |
| Cleanup/unload | PASS | `unloadScript=true`, `isScriptLoaded=false`, and no pending five-second callback appeared during the six-second post-unload window. |

### Monotonic journal measurements

| Requested | Samples | Minimum | Maximum | Mean | Median | Early | Missing | Duplicate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 350 ms | 20 | 350.257 ms | 350.575 ms | 350.383 ms | 350.369 ms | 0 | 0 | 0 |
| 500 ms | 20 | 500.361 ms | 500.654 ms | 500.499 ms | 500.492 ms | 0 | 0 | 0 |

The measurements use the journald monotonic timestamp preceding each marker.
They do not use JavaScript wall-clock time. Late delivery remains permitted by
Qt and is reported rather than treated as a real-time guarantee.

## Required Plasma 6.4 gates

| Environment | Status | Missing evidence |
|---|---|---|
| Plasma/KWin 6.4 Wayland | **NOT RUN** | A real 6.4 Wayland session must run the committed probe and retain environment, journal, verifier, and cleanup output. |
| Plasma/KWin 6.4 X11 | **NOT RUN** | A real 6.4 X11 session must run the same probe and retain the same evidence. |

No VM or KWin build environment was created because that requires separate
permission.

## Decision

**PARTIAL / BLOCKED.** The timer-backed active-key design is technically
plausible and passes the available newer Wayland smoke-test, but it is not yet
a supported architecture for this project.

Production integration remains blocked until both Plasma/KWin 6.4 gates pass.
If either environment cannot construct/configure `QTimer`, cannot read back
`PreciseTimer`, fires early, fails cancellation/cleanup, or differs materially
between Wayland and X11, this approach is **FAIL** and the next architecture to
investigate is a small supported native/D-Bus boundary backed by
`QElapsedTimer`. That native boundary is not part of this spike.

If both gates pass, the future cooldown contract is:

- one active one-shot timer per `outputName + position`;
- denied events do not call `start()` and therefore do not move the deadline;
- timeout removes/releases the active key;
- `cooldownMs: 0` bypasses timer gating;
- no absolute JavaScript clock is needed;
- `decideCooldown()` remains a semantic reference model rather than receiving
  wall-clock timestamps.
