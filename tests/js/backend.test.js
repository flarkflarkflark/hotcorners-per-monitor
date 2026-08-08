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

function makeV3Binding(action, cooldownMs = 350, extra = {}) {
    return Object.assign({tap: action, cooldownMs}, extra);
}

function makeV3Context(kind, monitors, extra = {}) {
    return Object.assign({kind, monitors}, extra);
}

function makeV3Config(contexts, extra = {}) {
    return Object.assign({schemaVersion: 3, contexts}, extra);
}

function setRuntimeContext(backend, {
    activityId = "",
    desktopIdByOutput = {},
} = {}) {
    backend.workspace.currentActivity = activityId;
    backend.workspace.currentDesktopForScreen = screen => {
        if (!screen || !screen.name) {
            return null;
        }
        if (Object.prototype.hasOwnProperty.call(desktopIdByOutput, screen.name)) {
            const desktopId = desktopIdByOutput[screen.name];
            if (!desktopId) {
                return null;
            }
            return {id: desktopId};
        }
        return null;
    };
}

function makeRuntimeConfig({
    defaultMonitors = {},
    activityMonitors = null,
    desktopMonitors = null,
    combinedMonitors = null,
    extraContexts = {},
    activityId = "work",
    desktopId = "desk-1",
    extraRoot = {},
} = {}) {
    const contexts = Object.assign({}, extraContexts);
    if (defaultMonitors !== null) {
        contexts.default = makeV3Context("default", defaultMonitors);
    }
    if (activityMonitors !== null) {
        contexts[`activity:${activityId}`] = makeV3Context("activity", activityMonitors, {activityId});
    }
    if (desktopMonitors !== null) {
        contexts[`desktop:${desktopId}`] = makeV3Context("desktop", desktopMonitors, {desktopId});
    }
    if (combinedMonitors !== null) {
        contexts[`activity:${activityId}|desktop:${desktopId}`] = makeV3Context(
            "activityDesktop",
            combinedMonitors,
            {activityId, desktopId},
        );
    }
    return makeV3Config(contexts, extraRoot);
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

function makeSignalHarness() {
    const callbacks = [];
    return {
        callbacks,
        connectCount: 0,
        disconnectCount: 0,
        connect(callback) {
            callbacks.push(callback);
            this.connectCount++;
        },
        disconnect(callback) {
            const index = callbacks.indexOf(callback);
            if (index !== -1) {
                callbacks.splice(index, 1);
            }
            this.disconnectCount++;
        },
        emit(...args) {
            for (const callback of callbacks.slice()) {
                callback(...args);
            }
        },
    };
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
        cursorPosChanged: makeSignalHarness(),
        screensChanged: makeSignalHarness(),
        screenAt(pos) {
            if (!pos) return null;
            for (const screen of workspace.screens) {
                const g = screen.geometry;
                if (pos.x >= g.x && pos.x < g.x + g.width &&
                    pos.y >= g.y && pos.y < g.y + g.height) {
                    return screen;
                }
            }
            return null;
        },
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
            if (!callDBusImpl) {
                return undefined;
            }
            const reply = callDBusImpl(...args);
            // Real callDBus is always asynchronous: it returns nothing and
            // passes the D-Bus reply values to the trailing callback. Model
            // that here so these tests exercise the real reply path.
            const callback = args[args.length - 1];
            if (typeof callback === "function" && reply !== undefined) {
                callback(reply);
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

function setCursor(backend, x, y) {
    backend.workspace.cursorPos = {x, y};
    backend.workspace.cursorPosChanged.emit();
}

function lastDbusCall(backend) {
    return backend.dbusCalls[backend.dbusCalls.length - 1];
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

test("runtime load migrates v0.1 to v0.3 in memory without writing", () => {
    const backend = createBackend({config: legacyConfig});

    const config = plain(backend.context.loadRuntimeConfig());

    assert.equal(config.schemaVersion, 3);
    assert.equal(config.contexts.default.monitors["DP-1"].TopLeft.cooldownMs, 0);
    assert.deepEqual(backend.writes, []);
});

test("context precedence chooses combined, activity, desktop, then default", () => {
    const config = makeRuntimeConfig({
        defaultMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
            },
        },
        activityMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Activity"}),
            },
        },
        desktopMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Desktop"}),
            },
        },
        combinedMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Combined"}, 900),
            },
        },
    });

    const cases = [
        {
            name: "combined",
            setup(backend) {
                setRuntimeContext(backend, {
                    activityId: "work",
                    desktopIdByOutput: {"DP-1": "desk-1"},
                });
            },
            expectedName: "Combined",
            expectedCooldown: 900,
        },
        {
            name: "activity",
            setup(backend) {
                setRuntimeContext(backend, {
                    activityId: "work",
                });
            },
            expectedName: "Activity",
            expectedCooldown: 350,
        },
        {
            name: "desktop",
            setup(backend) {
                setRuntimeContext(backend, {
                    desktopIdByOutput: {"DP-1": "desk-1"},
                });
            },
            expectedName: "Desktop",
            expectedCooldown: 350,
        },
        {
            name: "default",
            setup(backend) {
                setRuntimeContext(backend);
            },
            expectedName: "Default",
            expectedCooldown: 350,
        },
    ];

    for (const scenario of cases) {
        const backend = createBackend({config});
        scenario.setup(backend);
        backend.workspace.cursorPos = {x: 10, y: 10};

        callbackFor(backend, "ElectricTopLeft")();

        assert.equal(backend.dbusCalls.length, 1, scenario.name);
        assert.deepEqual(backend.dbusCalls[0], [
            "org.kde.kglobalaccel",
            "/component/kwin",
            "org.kde.kglobalaccel.Component",
            "invokeShortcut",
            scenario.expectedName,
        ]);
        assert.equal(backend.timers.length, 1, scenario.name);
        assert.equal(backend.timers[0].intervalMs, scenario.expectedCooldown, scenario.name);
        assert.deepEqual(backend.writes, []);
    }
});

test("explicit none blocks fallback and starts no timer", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "none"}),
                },
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
    assert.deepEqual(backend.writes, []);
});

test("malformed exact action falls through to default", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({
                        type: "command",
                        program: "",
                        arguments: ["bad"],
                    }),
                },
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.dbusCalls[0][0], "org.kde.kglobalaccel");
    assert.equal(backend.dbusCalls[0][4], "Default");
    assert.equal(backend.timers.length, 1);
    assert.deepEqual(backend.writes, []);
});

test("malformed default action resolves to no dispatch", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({
                        type: "command",
                        program: "",
                        arguments: ["bad"],
                    }),
                },
            },
            combinedMonitors: {
                "DP-1": {},
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
    assert.deepEqual(backend.writes, []);
});

test("missing contexts.default produces no dispatch", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: null,
            activityMonitors: {
                "HDMI-A-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Activity"}),
                },
            },
            combinedMonitors: {
                "DP-1": {},
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
});

test("output and position isolation are enforced by runtime resolution", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "HDMI-A-1": {
                    TopRight: makeV3Binding({type: "shortcut", component: "kwin", name: "Wrong output"}),
                },
            },
            combinedMonitors: {
                "HDMI-A-1": {
                    TopRight: makeV3Binding({type: "shortcut", component: "kwin", name: "Wrong position"}),
                },
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
});

test("no inheritance from another non-default context", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: null,
            activityMonitors: {
                "HDMI-A-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Other activity"}),
                },
            },
            combinedMonitors: {
                "DP-1": {},
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
});

test("command actions resolve through exact context and fallback", () => {
    const exactBackend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({
                        type: "command",
                        program: "/usr/bin/printf",
                        arguments: ["%s\\n", "exact"],
                    }),
                },
            },
        }),
    });
    setRuntimeContext(exactBackend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    exactBackend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(exactBackend, "ElectricTopLeft")();

    assert.equal(exactBackend.dbusCalls.length, 1);
    assert.equal(exactBackend.dbusCalls[0][0], "org.flark.HotCorners.CommandRunner");
    assert.equal(exactBackend.dbusCalls[0][4], "/usr/bin/printf");
    assert.equal(JSON.parse(exactBackend.dbusCalls[0][5])[1], "exact");

    const fallbackBackend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({
                        type: "command",
                        program: "/usr/bin/printf",
                        arguments: ["%s\\n", "fallback"],
                    }),
                },
            },
            combinedMonitors: {
                "DP-1": {},
            },
        }),
    });
    setRuntimeContext(fallbackBackend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    fallbackBackend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(fallbackBackend, "ElectricTopLeft")();

    assert.equal(fallbackBackend.dbusCalls.length, 1);
    assert.equal(fallbackBackend.dbusCalls[0][0], "org.flark.HotCorners.CommandRunner");
    assert.equal(JSON.parse(fallbackBackend.dbusCalls[0][5])[1], "fallback");
});

test("resolved cooldown override and fallback cooldown remain distinct", () => {
    const overrideBackend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}, 350),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Exact"}, 900),
                },
            },
        }),
    });
    setRuntimeContext(overrideBackend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    overrideBackend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(overrideBackend, "ElectricTopLeft")();

    assert.equal(overrideBackend.timers[0].intervalMs, 900);
    assert.equal(overrideBackend.dbusCalls[0][4], "Exact");

    const fallbackBackend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}, 350),
                },
            },
            combinedMonitors: {
                "DP-1": {},
            },
        }),
    });
    setRuntimeContext(fallbackBackend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    fallbackBackend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(fallbackBackend, "ElectricTopLeft")();

    assert.equal(fallbackBackend.timers[0].intervalMs, 350);
    assert.equal(fallbackBackend.dbusCalls[0][4], "Default");
});

test("cooldown denial and timeout release stay unchanged under context resolution", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}, 350),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Exact"}, 900),
                },
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    trigger();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.timers.length, 1);
    assert.equal(totalStartCalls(backend.timers), 1);

    backend.timers[0].fireTimeout();
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(totalStartCalls(backend.timers), 2);
});

test("config reload clears resolved timers and re-evaluates context", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Before"}, 350),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Before exact"}, 900),
                },
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};
    const trigger = callbackFor(backend, "ElectricTopLeft");

    trigger();
    assert.equal(backend.timers.length, 1);

    backend.setConfig(makeRuntimeConfig({
        defaultMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "After"}, 350),
            },
        },
        combinedMonitors: null,
    }));
    backend.context.loadConfig();

    assert.equal(backend.timers[0].stopCallCount, 1);

    setRuntimeContext(backend, {});
    trigger();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(backend.dbusCalls[1][4], "After");
});

test("cleanup stops resolved timers and stale timeout callbacks do nothing", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}, 350),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Exact"}, 900),
                },
            },
        }),
    });
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();
    const dispatchCount = backend.dbusCalls.length;

    backend.context.cleanupRuntime();
    assert.equal(backend.timers[0].stopCallCount, 1);

    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, dispatchCount);
});

test("resolver is called exactly once per trigger", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
                },
            },
            combinedMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Exact"}),
                },
            },
        }),
    });
    let resolveCalls = 0;
    const originalResolve = backend.context.resolveContextActionCascade;
    backend.context.resolveContextActionCascade = function(...args) {
        resolveCalls++;
        return originalResolve(...args);
    };
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(resolveCalls, 1);
});

test("unknown extension fields do not affect runtime resolution", () => {
    const input = makeRuntimeConfig({
        defaultMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({
                    type: "shortcut",
                    component: "kwin",
                    name: "Default",
                }, 350, {
                    xTestBindingHint: "binding",
                }),
            },
        },
        combinedMonitors: {
            "DP-1": {
                TopLeft: makeV3Binding({
                    type: "shortcut",
                    component: "kwin",
                    name: "Exact",
                }, 900, {
                    xTestBindingHint: "exact-binding",
                }),
            },
        },
        extraRoot: {xTestRootHint: true},
    });
    input.contexts.default.xTestContextHint = "default-context";
    input.contexts["activity:work|desktop:desk-1"].xTestContextHint = "exact-context";
    input.contexts.default.monitors["DP-1"].TopLeft.tap.xTestActionHint = "default-action";
    input.contexts["activity:work|desktop:desk-1"].monitors["DP-1"].TopLeft.tap.xTestActionHint = "exact-action";

    const original = structuredClone(input);
    const backend = createBackend({config: input});
    setRuntimeContext(backend, {
        activityId: "work",
        desktopIdByOutput: {"DP-1": "desk-1"},
    });
    backend.workspace.cursorPos = {x: 10, y: 10};

    callbackFor(backend, "ElectricTopLeft")();
    backend.context.loadRuntimeConfig();

    assert.deepEqual(input, original);
    assert.equal(backend.dbusCalls[0][4], "Exact");
});

test("prototype-sensitive activity ids resolve safely through the runtime context key", () => {
    const ids = ["__proto__", "constructor", "toString"];
    for (const activityId of ids) {
        const backend = createBackend({
            config: makeRuntimeConfig({
                defaultMonitors: {
                    "DP-1": {
                        TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
                    },
                },
                extraContexts: {
                    [`activity:${activityId}`]: makeV3Context("activity", {
                        "DP-1": {
                            TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: activityId}),
                        },
                    }, {activityId}),
                },
            }),
        });
        setRuntimeContext(backend, {activityId});
        backend.workspace.cursorPos = {x: 10, y: 10};

        callbackFor(backend, "ElectricTopLeft")();

        assert.equal(backend.dbusCalls.length, 1);
        assert.equal(backend.dbusCalls[0][4], activityId);
    }
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

test("tap-linger runtime: immediate tap without linger dispatches immediately and creates no linger timer", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Overview"}),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.timers.some(timer => timer.intervalMs === 500), false);
});

test("tap-linger runtime: valid linger starts one timer with the documented properties", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].singleShot, true);
    assert.equal(backend.timers[0].timerType, 0);
    assert.equal(backend.timers[0].intervalMs, 500);
    assert.equal(backend.timers[0].startCallCount, 1);
    assert.equal(backend.timers[0].timeoutConnectCount, 1);
});

test("tap-linger runtime: timeout emits linger exactly once", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.timers[0].fireTimeout();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(lastDbusCall(backend)[4], "Show Desktop");

    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, 1);
});

test("tap-linger runtime: leaving before the threshold emits tap and stops the linger timer", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    setCursor(backend, 9, 0);

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(lastDbusCall(backend)[4], "Overview");
    assert.equal(backend.timers[0].stopCallCount >= 1, true);

    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, 1);
});

test("tap-linger runtime: exact 8 px stays pending until timeout", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    setCursor(backend, 8, 8);

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers[0].active, true);

    backend.timers[0].fireTimeout();
    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(lastDbusCall(backend)[4], "Show Desktop");
});

test("tap-linger runtime: duplicate edge enter while pending is ignored", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.timers.length, 1);
    assert.equal(backend.timers[0].startCallCount, 1);
    assert.equal(backend.dbusCalls.length, 0);
});

test("tap-linger runtime: malformed linger acts like no linger and valid tap still dispatches immediately", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "", name: ""}},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.timers.some(timer => timer.intervalMs === 500), false);
});

test("tap-linger runtime: command action can dispatch on linger timeout", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "command", program: "/usr/bin/printf", arguments: ["linger"]}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.timers[0].fireTimeout();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(lastDbusCall(backend)[0], "org.flark.HotCorners.CommandRunner");
});

test("tap-linger runtime: resolved cooldown is applied after linger dispatch", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        900,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.timers[0].fireTimeout();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(activeTimerCount(backend.timers), 1);

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    assert.equal(backend.dbusCalls.length, 1);
});

test("tap-linger runtime: exact context override wins over default linger", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Default"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Default Linger"}, lingerMs: 500},
                    ),
                },
            },
            activityMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Exact"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Exact Linger"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setRuntimeContext(backend, {activityId: "work"});
    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.timers[0].fireTimeout();

    assert.equal(lastDbusCall(backend)[4], "Exact Linger");
});

test("tap-linger runtime: omission falls back to default linger", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Default"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Default Linger"}, lingerMs: 500},
                    ),
                },
            },
            activityMonitors: {
                "DP-1": {},
            },
        }),
    });

    setRuntimeContext(backend, {activityId: "work"});
    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.timers[0].fireTimeout();

    assert.equal(lastDbusCall(backend)[4], "Default Linger");
});

test("tap-linger runtime: explicit none blocks fallback and creates no linger timer", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "shortcut", component: "kwin", name: "Default"}),
                },
            },
            activityMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding({type: "none"}),
                },
            },
        }),
    });

    setRuntimeContext(backend, {activityId: "work"});
    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers.length, 0);
});

test("tap-linger runtime: reload and cleanup stop active linger timers and stale callbacks do nothing", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    const lingerTimer = backend.timers[0];

    backend.context.loadConfig();
    assert.equal(lingerTimer.stopCallCount, 1);
    setCursor(backend, 9, 0);
    lingerTimer.fireTimeout();
    assert.equal(backend.dbusCalls.length, 0);

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.context.cleanupRuntime();
    assert.equal(backend.timers[1].stopCallCount, 1);
    backend.timers[1].fireTimeout();
    assert.equal(backend.dbusCalls.length, 0);
});

test("tap-linger runtime: timer constructor, connect and start failures fail safe", () => {
    const failureCases = [
        {name: "constructor", qtimerOptions: {constructorThrows: true}},
        {name: "connect", qtimerOptions: {perTimer: [{connectThrows: true}]}},
        {name: "start", qtimerOptions: {perTimer: [{startThrows: true}]}},
    ];

    for (const failureCase of failureCases) {
        const backend = createBackend({
            config: makeRuntimeConfig({
                defaultMonitors: {
                    "DP-1": {
                        TopLeft: makeV3Binding(
                            {type: "shortcut", component: "kwin", name: "Overview"},
                            350,
                            {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                        ),
                    },
                },
            }),
            qtimerOptions: failureCase.qtimerOptions,
        });

        setCursor(backend, 10, 10);
        callbackFor(backend, "ElectricTopLeft")();

        assert.equal(backend.dbusCalls.length, 0, failureCase.name);
        assert.equal(
            backend.prints.some(args => args.join(" ").includes("failed to start linger timer")),
            true,
            failureCase.name,
        );
    }
});

test("tap-linger runtime: invalid cursor data cancels pending interactions without dispatch", () => {
    const backend = createBackend({
        config: makeRuntimeConfig({
            defaultMonitors: {
                "DP-1": {
                    TopLeft: makeV3Binding(
                        {type: "shortcut", component: "kwin", name: "Overview"},
                        350,
                        {linger: {type: "shortcut", component: "kwin", name: "Show Desktop"}, lingerMs: 500},
                    ),
                },
            },
        }),
    });

    setCursor(backend, 10, 10);
    callbackFor(backend, "ElectricTopLeft")();
    backend.workspace.cursorPos = {x: "bad", y: 0};
    backend.workspace.cursorPosChanged.emit();

    assert.equal(backend.dbusCalls.length, 0);
    assert.equal(backend.timers[0].stopCallCount, 1);
});
