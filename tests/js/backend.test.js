const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");
const legacyConfig = readFixture("v0.1-config.json");
const v2Config = readFixture("v0.2-migrated-config.json");
const extensionConfig = readFixture("v0.2-config-with-extensions.json");

function makeTimerGateConfig() {
    return {
        schemaVersion: 2,
        monitors: {
            "DP-1": {
                TopLeft: {
                    action: {type: "shortcut", component: "kwin", name: "Overview"},
                    cooldownMs: 350,
                },
                Top: {
                    action: {type: "shortcut", component: "kwin", name: "Present Windows"},
                    cooldownMs: 350,
                },
                BottomRight: {
                    action: {type: "none"},
                    cooldownMs: 350,
                },
            },
            "HDMI-A-1": {
                TopRight: {
                    action: {type: "shortcut", component: "ksmserver", name: "Lock Session"},
                    cooldownMs: 350,
                },
                TopLeft: {
                    action: {type: "shortcut", component: "kwin", name: "Overview"},
                    cooldownMs: 350,
                },
            },
        },
    };
}

function makeCommandGateConfig() {
    return {
        schemaVersion: 2,
        monitors: {
            "DP-1": {
                TopLeft: {
                    action: {
                        type: "command",
                        program: "/usr/bin/printf",
                        arguments: ["%s\\n", "hello world"],
                    },
                    cooldownMs: 350,
                },
                Top: {
                    action: {
                        type: "command",
                        program: "/usr/bin/echo",
                        arguments: ["hello; touch /tmp/x", "$(id)", "*.txt", "a | b", ">output"],
                    },
                    cooldownMs: 350,
                },
                Right: {
                    action: {
                        type: "command",
                        program: "/usr/bin/echo",
                        arguments: ["ok"],
                    },
                    cooldownMs: 0,
                },
                BottomLeft: {
                    action: {
                        type: "command",
                        program: "",
                        arguments: ["bad"],
                    },
                    cooldownMs: 350,
                },
                Bottom: {
                    action: {type: "none"},
                    cooldownMs: 350,
                },
                BottomRight: {
                    action: {type: "shortcut", component: "kwin", name: "Overview"},
                    cooldownMs: 350,
                },
            },
        },
    };
}

function readFixture(name) {
    return JSON.parse(
        fs.readFileSync(path.join(ROOT, "tests/fixtures", name), "utf8"),
    );
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

const ELECTRIC_BORDERS = {
    ElectricTopLeft: 0,
    ElectricTop: 1,
    ElectricTopRight: 2,
    ElectricRight: 3,
    ElectricBottomRight: 4,
    ElectricBottom: 5,
    ElectricBottomLeft: 6,
    ElectricLeft: 7,
};

function makeFakeQTimerHarness(options = {}) {
    const timers = [];

    function QTimer() {
        if (options.constructorThrows) {
            throw new Error("fake constructor failure");
        }

        const behavior = options.perTimer?.[timers.length] ?? {};
        const callbacks = [];
        const timer = {
            singleShot: false,
            timerType: undefined,
            intervalMs: undefined,
            startCallCount: 0,
            stopCallCount: 0,
            timeoutConnectCount: 0,
            timeoutFireCount: 0,
            active: false,
            setSingleShot(value) {
                if (behavior.setSingleShotThrows) {
                    throw new Error("fake setSingleShot failure");
                }
                timer.singleShot = Boolean(value);
            },
            setTimerType(value) {
                if (behavior.setTimerTypeThrows) {
                    throw new Error("fake setTimerType failure");
                }
                timer.timerType = value;
            },
            start(intervalMs) {
                if (behavior.startThrows) {
                    throw new Error("fake start failure");
                }
                timer.intervalMs = intervalMs;
                timer.startCallCount++;
                timer.active = true;
            },
            stop() {
                timer.stopCallCount++;
                timer.active = false;
            },
            isActive() {
                return timer.active;
            },
            timeout: {
                connect(callback) {
                    if (behavior.connectThrows) {
                        throw new Error("fake connect failure");
                    }
                    timer.timeoutConnectCount++;
                    callbacks.push(callback);
                },
            },
            fireTimeout() {
                timer.timeoutFireCount++;
                const toCall = callbacks.slice();
                if (timer.singleShot) {
                    timer.active = false;
                }
                for (const callback of toCall) {
                    callback();
                }
            },
        };

        timers.push(timer);
        return timer;
    }

    return {QTimer, timers};
}

function createBackend({
    config = legacyConfig,
    qtimerOptions = {},
    callDBusImpl,
    omitCallDBus = false,
} = {}) {
    let rawConfig = typeof config === "string"
        ? config
        : JSON.stringify(config);

    const callbacks = new Map();
    const dbusCalls = [];
    const prints = [];
    const writes = [];
    const qtimer = makeFakeQTimerHarness(qtimerOptions);

    const workspace = {
        cursorPos: {x: 100, y: 100},
        screens: [
            {
                name: "DP-1",
                geometry: {x: 0, y: 0, width: 3440, height: 1440},
            },
            {
                name: "HDMI-A-1",
                geometry: {x: 3440, y: 0, width: 1920, height: 1080},
            },
        ],
    };

    const contextValues = {
        KWin: ELECTRIC_BORDERS,
        workspace,
        QTimer: qtimer.QTimer,
        readConfig(key) {
            assert.equal(key, "MonitorConfigs");
            return rawConfig;
        },
        writeConfig(...args) {
            writes.push(args);
        },
        registerScreenEdge(border, callback) {
            callbacks.set(border, callback);
            return true;
        },
        print(...args) {
            prints.push(args);
        },
    };

    if (!omitCallDBus) {
        contextValues.callDBus = function(...args) {
            dbusCalls.push(args);
            if (callDBusImpl) {
                return callDBusImpl(...args);
            }
            return undefined;
        };
    }

    const context = vm.createContext(contextValues);

    vm.runInContext(backendSource, context, {filename: BACKEND_PATH});

    return {
        callbacks,
        context,
        dbusCalls,
        prints,
        workspace,
        writes,
        timers: qtimer.timers,
        setConfig(nextConfig) {
            rawConfig = typeof nextConfig === "string"
                ? nextConfig
                : JSON.stringify(nextConfig);
        },
    };
}

function callbackFor(backend, borderName) {
    return backend.callbacks.get(ELECTRIC_BORDERS[borderName]);
}

function totalStartCalls(timers) {
    return timers.reduce((sum, timer) => sum + timer.startCallCount, 0);
}

function activeTimerCount(timers) {
    return timers.filter(timer => timer.active).length;
}

test("registers all eight KWin electric borders", () => {
    const backend = createBackend();

    assert.equal(backend.callbacks.size, 8);
    assert.deepEqual(
        [...backend.callbacks.keys()].sort((a, b) => a - b),
        Object.values(ELECTRIC_BORDERS).sort((a, b) => a - b),
    );
});

test("dispatches a legacy shortcut for the output under the cursor", () => {
    const backend = createBackend();
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.deepEqual(backend.dbusCalls, [[
        "org.kde.kglobalaccel",
        "/component/kwin",
        "org.kde.kglobalaccel.Component",
        "invokeShortcut",
        "Overview",
    ]]);
});

test("command A/B/C: valid command dispatches one helper call with exact argv JSON", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 1);
    const [bus, objectPath, interfaceName, methodName, program, argumentsJson] = backend.dbusCalls[0];
    assert.equal(bus, "org.flark.HotCorners.CommandRunner");
    assert.equal(objectPath, "/CommandRunner");
    assert.equal(interfaceName, "org.flark.HotCorners.CommandRunner1");
    assert.equal(methodName, "Run");
    assert.equal(program, "/usr/bin/printf");
    assert.deepEqual(JSON.parse(argumentsJson), ["%s\\n", "hello world"]);

    const config = makeCommandGateConfig();
    const shellArgs = config.monitors["DP-1"].Top.action.arguments;
    backend.workspace.cursorPos = {x: 10, y: 10};
    callbackFor(backend, "ElectricTop")();
    assert.deepEqual(JSON.parse(backend.dbusCalls[1][5]), shellArgs);

    assert.equal(
        backend.dbusCalls.some(call => call[0] === "org.kde.kglobalaccel"),
        false,
    );
});

test("runtime load migrates v0.1 to v0.2 in memory without writing", () => {
    const backend = createBackend({config: legacyConfig});

    const config = plain(backend.context.loadRuntimeConfig());

    assert.equal(config.schemaVersion, 2);
    assert.equal(config.monitors["DP-1"].TopLeft.cooldownMs, 0);
    assert.deepEqual(backend.writes, []);
});

test("invalid JSON fails closed without writing or partial dispatch", () => {
    const backend = createBackend({config: '{"DP-1":{"TopLeft":'});

    callbackFor(backend, "ElectricTopLeft")();

    assert.deepEqual(backend.dbusCalls, []);
    assert.deepEqual(backend.writes, []);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("failed to load config")),
        true,
    );
});

test("A: first trigger starts one single-shot precise timer and dispatches once", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 3500, y: 10};

    callbackFor(backend, "ElectricTopRight")();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].singleShot, true);
    assert.equal(backend.timers[0].timerType, 0);
    assert.equal(backend.timers[0].intervalMs, 350);
    assert.equal(backend.timers[0].startCallCount, 1);
    assert.equal(backend.timers[0].active, true);
});

test("B: trigger during active cooldown is denied without restart", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 3500, y: 10};
    const trigger = callbackFor(backend, "ElectricTopRight");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].startCallCount, 1);
});

test("C and D: timeout releases cooldown and denied trigger does not shift deadline", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 3500, y: 10};
    const trigger = callbackFor(backend, "ElectricTopRight");

    trigger();
    trigger();

    assert.equal(totalStartCalls(backend.timers), 1);

    backend.timers[0].fireTimeout();
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(totalStartCalls(backend.timers), 2);
    assert.equal(activeTimerCount(backend.timers), 1);
});

test("E: cooldownMs zero bypasses timers and allows immediate repeats", () => {
    const config = makeTimerGateConfig();
    config.monitors["DP-1"].TopLeft.cooldownMs = 0;
    const backend = createBackend({config});
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(backend.timers.length, 0);
});

test("F: cooldown state is independent per output", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    const trigger = callbackFor(backend, "ElectricTopLeft");

    backend.workspace.cursorPos = {x: 3500, y: 10};
    trigger();
    backend.workspace.cursorPos = {x: 10, y: 10};
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(backend.timers.length, 2);
});

test("G: cooldown state is independent per position", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();
    callbackFor(backend, "ElectricTop")();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(backend.timers.length, 2);
});

test("H: none action dispatches nothing and starts no timer", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricBottomRight")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
});

test("I: invalid command action is ignored without timer state", () => {
    const config = makeCommandGateConfig();
    const backend = createBackend({config});
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricBottomLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
});

test("J: config reload clears cooldown state and stops active timers", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    const triggerTopLeft = callbackFor(backend, "ElectricTopLeft");
    const triggerTopRight = callbackFor(backend, "ElectricTopRight");

    backend.workspace.cursorPos = {x: 10, y: 10};
    triggerTopLeft();
    backend.workspace.cursorPos = {x: 3500, y: 10};
    triggerTopRight();

    assert.equal(backend.timers.length, 2);

    backend.setConfig(makeTimerGateConfig());
    backend.context.loadConfig();

    assert.equal(backend.timers[0].stopCallCount, 1);
    assert.equal(backend.timers[1].stopCallCount, 1);

    backend.workspace.cursorPos = {x: 10, y: 10};
    triggerTopLeft();
    assert.equal(backend.dbusCalls.length, 3);
});

test("K: cleanup stops timers and stale timeout callbacks become no-ops", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};
    callbackFor(backend, "ElectricTopLeft")();
    const shortcutCallsBefore = backend.dbusCalls.length;

    backend.context.cleanupRuntime();
    assert.equal(backend.timers[0].stopCallCount, 1);

    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, shortcutCallsBefore);

    callbackFor(backend, "ElectricTopLeft")();
    assert.equal(backend.dbusCalls.length, shortcutCallsBefore + 1);
});

test("L: dispatch failure still consumes cooldown and blocks retrigger", () => {
    let attempts = 0;
    const backend = createBackend({
        config: makeTimerGateConfig(),
        callDBusImpl() {
            attempts++;
            throw new Error("defensive invokeShortcut failure");
        },
    });
    backend.workspace.cursorPos = {x: 3500, y: 10};
    const trigger = callbackFor(backend, "ElectricTopRight");

    trigger();
    trigger();

    assert.equal(attempts, 1);
    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].active, true);

    backend.timers[0].fireTimeout();
    trigger();
    assert.equal(attempts, 2);
});

test("M: runtime never writes config while gating, reloading, or cleaning", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 3500, y: 10};
    const trigger = callbackFor(backend, "ElectricTopRight");

    trigger();
    trigger();
    backend.timers[0].fireTimeout();
    trigger();
    backend.context.loadConfig();
    backend.context.cleanupRuntime();

    assert.deepEqual(backend.writes, []);
});

test("N: timer constructor failure fails safe without dispatch or state", () => {
    const backend = createBackend({
        config: makeTimerGateConfig(),
        qtimerOptions: {constructorThrows: true},
    });
    backend.workspace.cursorPos = {x: 3500, y: 10};

    callbackFor(backend, "ElectricTopRight")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("failed to start cooldown timer")),
        true,
    );
});

test("O: timer start failure fails safe and leaves no active cooldown", () => {
    const backend = createBackend({
        config: makeTimerGateConfig(),
        qtimerOptions: {perTimer: [{startThrows: true}, {startThrows: true}]},
    });
    backend.workspace.cursorPos = {x: 3500, y: 10};
    const trigger = callbackFor(backend, "ElectricTopRight");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 2);
    assert.equal(activeTimerCount(backend.timers), 0);
});

test("P: timeout connect failure fails safe and leaves no cooldown", () => {
    const backend = createBackend({
        config: makeTimerGateConfig(),
        qtimerOptions: {perTimer: [{connectThrows: true}]},
    });
    backend.workspace.cursorPos = {x: 3500, y: 10};

    callbackFor(backend, "ElectricTopRight")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(activeTimerCount(backend.timers), 0);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("failed to start cooldown timer")),
        true,
    );
});

test("Q: at most one active cooldown entry exists per output and position", () => {
    const backend = createBackend({config: makeTimerGateConfig()});
    backend.workspace.cursorPos = {x: 3500, y: 10};
    const trigger = callbackFor(backend, "ElectricTopRight");

    trigger();
    trigger();
    trigger();

    assert.equal(backend.timers.length, 1);
    assert.equal(activeTimerCount(backend.timers), 1);

    backend.timers[0].fireTimeout();
    trigger();

    assert.equal(activeTimerCount(backend.timers), 1);
});

test("R: separator-like names are collision-safe for cooldown identity", () => {
    const config = {
        schemaVersion: 2,
        monitors: {
            "a:b": {
                TopLeft: {
                    action: {type: "shortcut", component: "kwin", name: "Overview"},
                    cooldownMs: 350,
                },
            },
            a: {
                TopLeft: {
                    action: {type: "shortcut", component: "kwin", name: "Overview"},
                    cooldownMs: 350,
                },
            },
        },
    };
    const backend = createBackend({config});
    backend.workspace.screens = [
        {name: "a:b", geometry: {x: 0, y: 0, width: 100, height: 100}},
        {name: "a", geometry: {x: 100, y: 0, width: 100, height: 100}},
    ];

    const trigger = callbackFor(backend, "ElectricTopLeft");
    backend.workspace.cursorPos = {x: 10, y: 10};
    trigger();
    backend.workspace.cursorPos = {x: 110, y: 10};
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(backend.timers.length, 2);
});

test("command D: cooldown blocks second command without timer restart", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].startCallCount, 1);
});

test("command E: timeout releases cooldown and next trigger dispatches again", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    backend.timers[0].fireTimeout();
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(totalStartCalls(backend.timers), 2);
});

test("command F: cooldown 0 allows immediate repeated helper calls", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricRight");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(backend.timers.length, 0);
});

test("command G: helper rejection logs error name and keeps cooldown active", () => {
    const backend = createBackend({
        config: makeCommandGateConfig(),
        callDBusImpl() {
            return [false, "program-not-found"];
        },
    });
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("command helper error: program-not-found")),
        true,
    );
    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].active, true);
});

test("command H: helper accepted result logs no error", () => {
    const backend = createBackend({
        config: makeCommandGateConfig(),
        callDBusImpl() {
            return [true, ""];
        },
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("command helper error")),
        false,
    );
});

test("command I: malformed helper responses fail safe with invalid-helper-response", () => {
    const malformedValues = [null, [true], ["yes", ""], [true, 1]];

    for (const malformed of malformedValues) {
        const backend = createBackend({
            config: makeCommandGateConfig(),
            callDBusImpl() {
                return malformed;
            },
        });
        backend.workspace.cursorPos = {x: 10, y: 10};

        callbackFor(backend, "ElectricTopLeft")();

        assert.equal(backend.dbusCalls.length, 1);
        assert.equal(
            backend.prints.some(args => args.join(" ").includes("command helper error: invalid-helper-response")),
            true,
        );
    }
});

test("command J: transport failure is logged and never retried", () => {
    let calls = 0;
    const backend = createBackend({
        config: makeCommandGateConfig(),
        callDBusImpl() {
            calls++;
            throw new Error("dbus transport down");
        },
    });
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    trigger();

    assert.equal(calls, 1);
    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("command helper error: transport-error")),
        true,
    );
});

test("command K: helper unavailable logs fail-safe and does not fallback", () => {
    const backend = createBackend({
        config: makeCommandGateConfig(),
        omitCallDBus: true,
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("command helper error: helper-unavailable")),
        true,
    );
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("invokeShortcut")),
        false,
    );
});

test("command L: invalid command argument shapes never consume cooldown", () => {
    const invalidActions = [
        {type: "command", program: "/usr/bin/echo", arguments: "no-array"},
        {type: "command", program: "/usr/bin/echo", arguments: ["ok", 1]},
    ];

    for (const action of invalidActions) {
        const config = makeCommandGateConfig();
        config.monitors["DP-1"].BottomLeft.action = action;
        const backend = createBackend({config});
        backend.workspace.cursorPos = {x: 10, y: 10};

        callbackFor(backend, "ElectricBottomLeft")();

        assert.equal(backend.dbusCalls.length, 0);
        assert.equal(backend.timers.length, 0);
    }
});

test("command N: reload clears command cooldown and stale timeout callback is harmless", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    assert.equal(backend.dbusCalls.length, 1);

    backend.setConfig(makeCommandGateConfig());
    backend.context.loadConfig();
    assert.equal(backend.timers[0].stopCallCount, 1);

    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, 1);

    trigger();
    assert.equal(backend.dbusCalls.length, 2);
});

test("command M: none and shortcut remain regression-free", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricBottom")();
    assert.equal(backend.dbusCalls.length, 0);

    callbackFor(backend, "ElectricBottomRight")();
    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.dbusCalls[0][0], "org.kde.kglobalaccel");
});

test("command N/P: cleanup removes stale command timers and each admission calls helper once", () => {
    const backend = createBackend({config: makeCommandGateConfig()});
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    assert.equal(backend.dbusCalls.length, 1);

    backend.context.cleanupRuntime();
    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, 1);

    trigger();
    assert.equal(backend.dbusCalls.length, 2);
});

test("command O: runtime never writes config for command outcomes", () => {
    const responses = [
        [true, ""],
        [false, "program-not-found"],
        null,
    ];

    for (const response of responses) {
        const backend = createBackend({
            config: makeCommandGateConfig(),
            callDBusImpl() {
                if (response === null) {
                    throw new Error("transport");
                }
                return response;
            },
        });
        backend.workspace.cursorPos = {x: 10, y: 10};

        const trigger = callbackFor(backend, "ElectricTopLeft");
        trigger();
        trigger();

        assert.deepEqual(backend.writes, []);
    }
});

test("command Q: logs omit command payload content", () => {
    const backend = createBackend({
        config: makeCommandGateConfig(),
        callDBusImpl() {
            return [false, "program-not-found"];
        },
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTop")();

    const joinedLogs = backend.prints.map(args => args.join(" ")).join("\n");
    assert.equal(joinedLogs.includes("hello; touch /tmp/x"), false);
    assert.equal(joinedLogs.includes("$(id)"), false);
    assert.equal(joinedLogs.includes("program-not-found"), true);
});

test("runtime normalization and dispatch do not mutate input fixtures", () => {
    const input = structuredClone(extensionConfig);
    const original = structuredClone(input);
    const backend = createBackend({config: input});

    callbackFor(backend, "ElectricTopLeft")();
    backend.context.loadRuntimeConfig();

    assert.deepEqual(input, original);
});
