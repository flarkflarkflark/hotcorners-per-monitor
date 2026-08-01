// Hot Corners Per Monitor — isolated QTimer capability probe
// SPDX-License-Identifier: GPL-3.0-or-later

const MARKER = "HCPM_QTIMER_PROBE ";
const RUN = "qtimer-probe-v1";
const SAMPLE_COUNT = 20;
const PRECISE_TIMER = 0; // Qt::PreciseTimer, per the official Qt::TimerType enum.
const timers = [];

function logMarker(fields) {
    fields.run = RUN;
    print(MARKER + JSON.stringify(fields));
}

function makeTimer(test, id, intervalMs, callback) {
    const timer = new QTimer();
    timer.singleShot = true;
    timer.timerType = PRECISE_TIMER;
    timer.interval = intervalMs;
    timer.timeout.connect(callback);
    timers.push(timer);

    logMarker({
        test,
        id,
        event: "configured",
        intervalMs,
        singleShot: timer.singleShot,
        timerType: timer.timerType,
        qtPreciseTimerAvailable:
            typeof Qt !== "undefined" &&
            typeof Qt.PreciseTimer !== "undefined",
        qtPreciseTimerValue:
            typeof Qt !== "undefined" &&
            typeof Qt.PreciseTimer !== "undefined"
                ? Qt.PreciseTimer
                : null,
    });
    return timer;
}

function startMeasuredSamples(intervalMs) {
    for (let sample = 0; sample < SAMPLE_COUNT; sample++) {
        const id = intervalMs + "-" + sample;
        const timer = makeTimer("interval", id, intervalMs, function() {
            logMarker({
                test: "interval",
                id,
                event: "timeout",
                intervalMs,
                sample,
            });
        });
        logMarker({
            test: "interval",
            id,
            event: "start",
            intervalMs,
            sample,
        });
        timer.start();
    }
}

function startCancelTest() {
    let timeoutCount = 0;
    const target = makeTimer("cancel", "target", 800, function() {
        timeoutCount++;
        logMarker({test: "cancel", id: "target", event: "unexpected-timeout"});
    });
    const stopper = makeTimer("cancel", "stopper", 100, function() {
        target.stop();
        logMarker({
            test: "cancel",
            id: "target",
            event: "stopped",
            active: target.active,
        });
    });
    const observer = makeTimer("cancel", "observer", 1000, function() {
        logMarker({
            test: "cancel",
            id: "target",
            event: "observed",
            timeoutCount,
        });
    });

    logMarker({test: "cancel", id: "target", event: "start", intervalMs: 800});
    target.start();
    stopper.start();
    observer.start();
}

function startIndependentTest() {
    const first = makeTimer("independent", "DP-1:TopLeft", 350, function() {
        logMarker({
            test: "independent",
            id: "DP-1:TopLeft",
            event: "timeout",
            intervalMs: 350,
        });
    });
    const second = makeTimer("independent", "HDMI-A-1:TopRight", 500, function() {
        logMarker({
            test: "independent",
            id: "HDMI-A-1:TopRight",
            event: "timeout",
            intervalMs: 500,
        });
    });

    logMarker({test: "independent", id: "DP-1:TopLeft", event: "start", intervalMs: 350});
    first.start();
    logMarker({test: "independent", id: "HDMI-A-1:TopRight", event: "start", intervalMs: 500});
    second.start();
}

function startRestartTest() {
    const target = makeTimer("restart", "target", 350, function() {
        logMarker({test: "restart", id: "target", event: "timeout", intervalMs: 350});
    });
    const restarter = makeTimer("restart", "restarter", 100, function() {
        logMarker({test: "restart", id: "target", event: "restart", intervalMs: 350});
        target.start();
    });

    logMarker({test: "restart", id: "target", event: "start", intervalMs: 350});
    target.start();
    restarter.start();
}

function startZeroIntervalTest() {
    const timer = makeTimer("zero", "target", 0, function() {
        logMarker({test: "zero", id: "target", event: "timeout", intervalMs: 0});
    });
    logMarker({test: "zero", id: "target", event: "start", intervalMs: 0});
    timer.start();
}

function scheduleUnloadTest() {
    const ready = makeTimer("suite", "ready", 1500, function() {
        const unloadTarget = makeTimer("unload", "target", 5000, function() {
            logMarker({test: "unload", id: "target", event: "unexpected-timeout"});
        });
        unloadTarget.start();
        logMarker({
            test: "suite",
            event: "ready-for-unload",
            unloadIntervalMs: 5000,
        });
    });
    ready.start();
}

try {
    logMarker({
        test: "constructor",
        event: "available",
        qtimerType: typeof QTimer,
    });
    startMeasuredSamples(350);
    startMeasuredSamples(500);
    startCancelTest();
    startIndependentTest();
    startRestartTest();
    startZeroIntervalTest();
    scheduleUnloadTest();
} catch (error) {
    logMarker({
        test: "suite",
        event: "fatal",
        errorName: error && error.name ? error.name : "Error",
        errorMessage: error && error.message ? error.message : String(error),
    });
}
