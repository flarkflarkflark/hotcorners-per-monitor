# KWin QTimer capability probe

This is isolated research code. It does not register screen edges, read or write
configuration, execute shortcuts, or import production code.

## Question

Can a KWin JavaScript script use one active `QTimer` per output/position as a
one-shot cooldown gate, without an absolute JavaScript clock?

## Safety

The probe is loaded ephemerally through KWin's scripting D-Bus API. It is not
installed as an enabled package and does not edit `kwinrc`. `uninstall-probe.sh`
unloads the script and destroys its timers.

The committed `metadata.json` makes the directory a valid, uniquely identified
KWin script package, but the smoke runner deliberately executes the source copy
directly to avoid persistent installation state.

## Official API basis

- KWin Plasma 6.4 source, pinned branch head `4018344761abe6b7c5fb7b1c22374799f769cae6`:
  - [`scripting.cpp`](https://invent.kde.org/plasma/kwin/-/blob/4018344761abe6b7c5fb7b1c22374799f769cae6/src/scripting/scripting.cpp)
  - [`scripting.h`](https://invent.kde.org/plasma/kwin/-/blob/4018344761abe6b7c5fb7b1c22374799f769cae6/src/scripting/scripting.h)
- [KWin scripting API](https://develop.kde.org/docs/plasma/kwin/api/)
- [Qt 6 QTimer](https://doc.qt.io/qt-6/qtimer.html)
- [Qt::TimerType](https://doc.qt.io/qt-6/qt.html#TimerType-enum)
- [Qt 6 QJSEngine](https://doc.qt.io/qt-6/qjsengine.html)

KWin exposes `ScriptTimer`, a `QTimer` subclass with a `Q_INVOKABLE`
constructor, through `QJSEngine::newQMetaObject()` as global `QTimer`. Qt's
QObject integration exposes properties, methods, and signals. The probe uses:

```javascript
const timer = new QTimer();
timer.singleShot = true;
timer.timerType = 0; // documented Qt::PreciseTimer enum value
timer.interval = 350;
timer.timeout.connect(callback);
timer.start();
```

The numeric value is used because the standalone KWin `QJSEngine` does not
document a global `Qt` namespace. Runtime readback must confirm
`timer.timerType === 0`; otherwise the capability fails rather than silently
using the default `Qt::CoarseTimer`.

Qt documents that `start()` on an active timer stops and restarts it. A future
cooldown implementation must therefore never call `start()` for a denied event.
Qt also guarantees that a `Qt::PreciseTimer` never times out early, although it
may time out late. Runtime evidence is still required for constructor exposure,
signal connection, enum/property readback, cancellation, independent lifecycle,
and unload behavior in KWin.

## Probe coverage

- constructor and timeout connection;
- 20 one-shot samples at 350 ms and 20 at 500 ms;
- `PreciseTimer` readback and single-shot readback;
- stop/cancel with an observation window;
- independent fictitious output/position timers;
- active-timer restart semantics;
- interval-zero QTimer semantics only;
- unload while a five-second timer is pending.

The probe never calls `Date.now()` or `performance.now()`. `verify-log.py` derives
durations from `journalctl --user -o short-monotonic` timestamps.

## Run

From an active Plasma session:

```bash
spikes/kwin-qtimer-probe/run-local-smoke.sh
```

Or manually:

```bash
spikes/kwin-qtimer-probe/install-probe.sh
# Wait for the ready-for-unload marker in the user journal.
spikes/kwin-qtimer-probe/uninstall-probe.sh
```

The smoke runner captures environment details, unloads the script before its
pending cleanup timer expires, waits six seconds, saves the monotonic journal,
runs the verifier, and confirms `isScriptLoaded=false`. Its temporary output
path is printed at completion. Bounded evidence from the supplementary local
run is stored under `results/plasma-6.7.3-wayland/`; raw journal output is not
committed.

## Interpretation

A successful local run proves only that environment. The architecture is not
proven until the same probe passes on both Plasma/KWin 6.4 Wayland and Plasma/
KWin 6.4 X11. Newer Plasma results are supplementary smoke evidence only.

For future production behavior, `cooldownMs: 0` must bypass timer gating; the
probe's zero-interval test records QTimer semantics and does not change that
contract.
