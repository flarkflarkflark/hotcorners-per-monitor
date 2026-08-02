// Hot Corners Per Monitor — KWin script backend
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Reads per-monitor hot-corner configuration from `readConfig("MonitorConfigs")`,
// which is stored as a JSON string in `~/.config/kwinrc` under the
// `[Script-hotcorners-per-monitor]` group.
//
// Configuration format:
// {
//   "<output-name>": {
//     "TopLeft":     { "type": "shortcut", "component": "kwin", "name": "Overview" },
//     "Top":         { "type": "none" },
//     "TopRight":    { ... },
//     "Right":       { ... },
//     "BottomRight": { ... },
//     "Bottom":      { ... },
//     "BottomLeft":  { ... },
//     "Left":        { ... }
//   },
//   "<other-output-name>": { ... }
// }
//
// Action types:
//   { "type": "none" }
//   { "type": "shortcut", "component": "<kglobalaccel-component>", "name": "<shortcut-name>" }
//
// Edits to this config become active on the next KWin reconfigure
// (`qdbus6 org.kde.KWin /KWin reconfigure`).

const POSITIONS = {
    TopLeft:     KWin.ElectricTopLeft,
    Top:         KWin.ElectricTop,
    TopRight:    KWin.ElectricTopRight,
    Right:       KWin.ElectricRight,
    BottomRight: KWin.ElectricBottomRight,
    Bottom:      KWin.ElectricBottom,
    BottomLeft:  KWin.ElectricBottomLeft,
    Left:        KWin.ElectricLeft,
};

const SCHEMA_VERSION = 2;
const DEFAULT_COOLDOWN_MS = 350;
const LEGACY_COOLDOWN_MS = 0;
const MAX_COOLDOWN_MS = 10000;
const COMMAND_RUNNER_BUS = "org.flark.HotCorners.CommandRunner";
const COMMAND_RUNNER_OBJECT_PATH = "/CommandRunner";
const COMMAND_RUNNER_INTERFACE = "org.flark.HotCorners.CommandRunner1";
const COMMAND_RUNNER_METHOD = "Run";
const MAX_COMMAND_ARGUMENTS = 128;
const MAX_COMMAND_ARGUMENT_BYTES = 16 * 1024;
const MAX_COMMAND_TOTAL_ARGUMENT_BYTES = 128 * 1024;
const MAX_COMMAND_PROGRAM_BYTES = 4096;

function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
}

function normalizeAction(action) {
    if (!isObject(action)) return null;

    const normalized = cloneJson(action);
    if (action.type === "none") {
        normalized.type = "none";
        return normalized;
    }
    if (action.type === "shortcut") {
        if (typeof action.component === "string" && action.component &&
            typeof action.name === "string" && action.name) {
            normalized.type = "shortcut";
            normalized.component = action.component;
            normalized.name = action.name;
            return normalized;
        }
        return null;
    }
    if (action.type === "command") {
        if (typeof action.program === "string" && action.program &&
            Array.isArray(action.arguments) &&
            action.arguments.every(arg => typeof arg === "string")) {
            normalized.type = "command";
            normalized.program = action.program;
            normalized.arguments = cloneJson(action.arguments);
            return normalized;
        }
    }
    return null;
}

function validCooldown(value) {
    return Number.isInteger(value) &&
           value >= 0 && value <= MAX_COOLDOWN_MS;
}

function utf8ByteLength(value) {
    return encodeURIComponent(value).replace(/%[A-F\d]{2}/g, "U").length;
}

function validateCommandAction(action) {
    if (!isObject(action) || action.type !== "command") {
        return {ok: false, errorName: "invalid-action-type"};
    }

    if (typeof action.program !== "string" || !action.program) {
        return {ok: false, errorName: "invalid-program"};
    }
    if (action.program.indexOf("\u0000") !== -1 ||
        utf8ByteLength(action.program) > MAX_COMMAND_PROGRAM_BYTES) {
        return {ok: false, errorName: "invalid-program"};
    }

    if (!Array.isArray(action.arguments) ||
        action.arguments.length > MAX_COMMAND_ARGUMENTS) {
        return {ok: false, errorName: "invalid-arguments"};
    }

    let totalBytes = 0;
    for (let i = 0; i < action.arguments.length; i++) {
        const argument = action.arguments[i];
        if (typeof argument !== "string" || argument.indexOf("\u0000") !== -1) {
            return {ok: false, errorName: "invalid-arguments"};
        }
        const size = utf8ByteLength(argument);
        if (size > MAX_COMMAND_ARGUMENT_BYTES) {
            return {ok: false, errorName: "invalid-arguments"};
        }
        totalBytes += size;
        if (totalBytes > MAX_COMMAND_TOTAL_ARGUMENT_BYTES) {
            return {ok: false, errorName: "invalid-arguments"};
        }
    }

    return {ok: true};
}

function buildCommandRequest(action) {
    const validation = validateCommandAction(action);
    if (!validation.ok) {
        throw new Error(validation.errorName);
    }

    return {
        bus: COMMAND_RUNNER_BUS,
        objectPath: COMMAND_RUNNER_OBJECT_PATH,
        interfaceName: COMMAND_RUNNER_INTERFACE,
        methodName: COMMAND_RUNNER_METHOD,
        program: action.program,
        argumentsJson: JSON.stringify(action.arguments),
    };
}

function normalizeCommandResult(rawResult) {
    if (Array.isArray(rawResult) && rawResult.length >= 2) {
        if (typeof rawResult[0] === "boolean" && typeof rawResult[1] === "string") {
            return {accepted: rawResult[0], errorName: rawResult[1]};
        }
        return {accepted: false, errorName: "invalid-helper-response"};
    }

    if (isObject(rawResult) && typeof rawResult.accepted === "boolean" &&
        typeof rawResult.errorName === "string") {
        return {accepted: rawResult.accepted, errorName: rawResult.errorName};
    }

    return {accepted: false, errorName: "invalid-helper-response"};
}

function invokeCommandHelper(action, helperClient) {
    const validation = validateCommandAction(action);
    if (!validation.ok) {
        return {accepted: false, errorName: validation.errorName};
    }

    if (!helperClient || typeof helperClient.call !== "function") {
        return {accepted: false, errorName: "helper-unavailable"};
    }

    const request = buildCommandRequest(action);
    try {
        const rawResult = helperClient.call(
            request.bus,
            request.objectPath,
            request.interfaceName,
            request.methodName,
            request.program,
            request.argumentsJson
        );
        return normalizeCommandResult(rawResult);
    } catch (_) {
        return {accepted: false, errorName: "transport-error"};
    }
}

function createCommandHelperClient() {
    if (typeof callDBus !== "function") {
        return null;
    }

    return {
        call(bus, objectPath, interfaceName, methodName, program, argumentsJson) {
            return callDBus(
                bus,
                objectPath,
                interfaceName,
                methodName,
                program,
                argumentsJson
            );
        },
    };
}

function createV2Binding(action, cooldownMs = DEFAULT_COOLDOWN_MS) {
    const normalizedAction = normalizeAction(action);
    if (!normalizedAction) throw new Error("invalid action");
    if (!validCooldown(cooldownMs)) throw new Error("invalid cooldownMs");
    return {action: normalizedAction, cooldownMs};
}

function decideCooldown(state, outputName, position, cooldownMs, nowMs) {
    if (!isObject(state) || !Array.isArray(state.entries)) {
        throw new TypeError("state.entries must be an array");
    }
    if (typeof outputName !== "string" || !outputName) {
        throw new TypeError("outputName must be a non-empty string");
    }
    if (typeof position !== "string" || !position) {
        throw new TypeError("position must be a non-empty string");
    }
    if (!validCooldown(cooldownMs)) {
        throw new RangeError("cooldownMs must be a non-negative integer");
    }
    if (typeof nowMs !== "number" || !Number.isFinite(nowMs) || nowMs < 0) {
        throw new RangeError("nowMs must be a finite non-negative number");
    }

    const entryIndex = state.entries.findIndex(entry =>
        isObject(entry) &&
        entry.outputName === outputName &&
        entry.position === position
    );
    if (entryIndex === -1) {
        const entries = state.entries.slice();
        entries.push({outputName, position, lastTriggeredMs: nowMs});
        return {
            allowed: true,
            reason: "first-trigger",
            state: Object.assign({}, state, {entries}),
        };
    }

    const entry = state.entries[entryIndex];
    const lastTriggeredMs = entry.lastTriggeredMs;
    if (typeof lastTriggeredMs !== "number" ||
        !Number.isFinite(lastTriggeredMs) || lastTriggeredMs < 0) {
        throw new TypeError("state contains an invalid lastTriggeredMs");
    }
    if (nowMs < lastTriggeredMs) {
        return {allowed: false, reason: "clock-regression", state};
    }
    if (nowMs - lastTriggeredMs < cooldownMs) {
        return {allowed: false, reason: "cooldown-active", state};
    }

    const entries = state.entries.slice();
    entries[entryIndex] = Object.assign({}, entry, {lastTriggeredMs: nowMs});
    return {
        allowed: true,
        reason: "cooldown-elapsed",
        state: Object.assign({}, state, {entries}),
    };
}

function normalizeMonitors(monitors, legacy) {
    if (!isObject(monitors)) throw new Error("monitors must be an object");

    const normalized = {};
    for (const outputName of Object.keys(monitors)) {
        const monitor = monitors[outputName];
        if (!outputName || !isObject(monitor)) continue;

        const normalizedMonitor = legacy ? {} : cloneJson(monitor);
        for (const position of Object.keys(monitor)) {
            if (!Object.prototype.hasOwnProperty.call(POSITIONS, position)) continue;

            if (!legacy) {
                delete normalizedMonitor[position];
            }

            if (legacy) {
                const action = normalizeAction(monitor[position]);
                if (!action) continue;
                normalizedMonitor[position] = {
                    action,
                    cooldownMs: LEGACY_COOLDOWN_MS,
                };
                continue;
            }

            const value = monitor[position];
            if (!isObject(value)) continue;
            const action = normalizeAction(value.action);
            if (!action || !validCooldown(value.cooldownMs)) continue;
            const binding = cloneJson(value);
            binding.action = action;
            binding.cooldownMs = value.cooldownMs;
            normalizedMonitor[position] = binding;
        }
        normalized[outputName] = normalizedMonitor;
    }
    return normalized;
}

function normalizeConfigToV2(config) {
    if (!isObject(config)) throw new Error("configuration root must be an object");

    if (!Object.prototype.hasOwnProperty.call(config, "schemaVersion")) {
        return {
            schemaVersion: SCHEMA_VERSION,
            monitors: normalizeMonitors(config, true),
        };
    }
    if (config.schemaVersion !== SCHEMA_VERSION) {
        throw new Error("unsupported schema version: " + config.schemaVersion);
    }

    const normalized = cloneJson(config);
    normalized.schemaVersion = SCHEMA_VERSION;
    normalized.monitors = normalizeMonitors(config.monitors, false);
    return normalized;
}

let runtimeConfig = {schemaVersion: SCHEMA_VERSION, monitors: {}};
let cooldownTimers = [];

function loadRuntimeConfig() {
    const raw = readConfig("MonitorConfigs", "{}");
    return normalizeConfigToV2(JSON.parse(raw));
}

function stopTimer(timer) {
    if (!timer) return;
    try {
        if (typeof timer.stop === "function") {
            timer.stop();
        }
    } catch (_) {
        // best-effort cleanup only
    }
}

function clearAllCooldownTimers() {
    for (let i = 0; i < cooldownTimers.length; i++) {
        stopTimer(cooldownTimers[i].timer);
    }
    cooldownTimers = [];
}

function findCooldownTimerIndex(outputName, position) {
    for (let i = 0; i < cooldownTimers.length; i++) {
        const entry = cooldownTimers[i];
        if (entry.outputName === outputName && entry.position === position) {
            return i;
        }
    }
    return -1;
}

function removeCooldownTimer(outputName, position, timer) {
    for (let i = 0; i < cooldownTimers.length; i++) {
        const entry = cooldownTimers[i];
        if (entry.outputName !== outputName || entry.position !== position) {
            continue;
        }
        if (timer && entry.timer !== timer) {
            continue;
        }
        cooldownTimers.splice(i, 1);
        return;
    }
}

function isTimerActive(timer) {
    if (!timer) return false;
    if (typeof timer.isActive === "function") {
        return !!timer.isActive();
    }
    return !!timer.active;
}

function isCooldownActive(outputName, position) {
    const index = findCooldownTimerIndex(outputName, position);
    if (index === -1) return false;
    const timer = cooldownTimers[index].timer;
    if (isTimerActive(timer)) {
        return true;
    }
    cooldownTimers.splice(index, 1);
    return false;
}

function beginCooldown(outputName, position, cooldownMs) {
    let timer;
    try {
        timer = new QTimer();

        if (typeof timer.setSingleShot === "function") {
            timer.setSingleShot(true);
        } else {
            timer.singleShot = true;
        }

        if (typeof timer.setTimerType === "function") {
            timer.setTimerType(0);
        } else {
            timer.timerType = 0;
        }

        timer.timeout.connect(function() {
            removeCooldownTimer(outputName, position, timer);
        });

        timer.start(cooldownMs);

        if (!isTimerActive(timer)) {
            throw new Error("timer is not active after start");
        }
    } catch (e) {
        stopTimer(timer);
        print("hotcorners-per-monitor: failed to start cooldown timer:", e);
        return false;
    }

    removeCooldownTimer(outputName, position);
    cooldownTimers.push({outputName, position, timer});
    return true;
}

function loadConfig() {
    clearAllCooldownTimers();
    try {
        runtimeConfig = loadRuntimeConfig();
        print("hotcorners-per-monitor: config loaded for outputs:",
              Object.keys(runtimeConfig.monitors).join(", ") || "(none)");
    } catch (e) {
        print("hotcorners-per-monitor: failed to load config:", e);
        runtimeConfig = {schemaVersion: SCHEMA_VERSION, monitors: {}};
    }
}

function cleanupRuntime() {
    clearAllCooldownTimers();
}

function getScreenAtCursor() {
    const pos = workspace.cursorPos;
    const screens = workspace.screens;
    for (let i = 0; i < screens.length; i++) {
        const g = screens[i].geometry;
        if (pos.x >= g.x && pos.x < g.x + g.width &&
            pos.y >= g.y && pos.y < g.y + g.height) {
            return screens[i];
        }
    }
    return null;
}

function isDispatchableAction(action) {
    if (!action || action.type === "none") {
        return false;
    }

    if (action.type === "shortcut") {
        return typeof action.component === "string" &&
               action.component &&
               typeof action.name === "string" &&
               action.name;
    }

    if (action.type === "command") {
        return validateCommandAction(action).ok;
    }

    return false;
}

function executeAction(action) {
    if (action.type === "shortcut") {
        const component = action.component;
        const name = action.name;
        callDBus(
            "org.kde.kglobalaccel",
            "/component/" + component,
            "org.kde.kglobalaccel.Component",
            "invokeShortcut",
            name
        );
        return;
    }

    if (action.type === "command") {
        const result = invokeCommandHelper(action, createCommandHelperClient());
        if (!result.accepted) {
            print("hotcorners-per-monitor: command helper error:", result.errorName);
        }
    }
}

function handleCorner(positionName) {
    const screen = getScreenAtCursor();
    if (!screen) return;
    const outputName = screen.name;
    if (!outputName) return;

    const monitor = runtimeConfig.monitors[outputName];
    if (!monitor) return;

    const binding = monitor[positionName];
    if (!binding || !isObject(binding)) return;

    const action = binding.action;
    if (!isDispatchableAction(action)) return;

    const cooldownMs = binding.cooldownMs;
    if (!validCooldown(cooldownMs)) return;

    if (cooldownMs > 0) {
        if (isCooldownActive(outputName, positionName)) {
            return;
        }
        if (!beginCooldown(outputName, positionName, cooldownMs)) {
            return;
        }
    }

    try {
        executeAction(action);
    } catch (e) {
        print("hotcorners-per-monitor: failed to invoke action:", e);
    }
}

// Bootstrap: load config + register all 8 corners/edges
loadConfig();

for (const positionName of Object.keys(POSITIONS)) {
    const border = POSITIONS[positionName];
    registerScreenEdge(border, function() {
        handleCorner(positionName);
    });
}
