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
const RUNTIME_SCHEMA_VERSION = 3;
const DEFAULT_COOLDOWN_MS = 350;
const DEFAULT_LINGER_MS = 500;
const DEFAULT_STAY_ZONE_PX = 8;
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

function normalizeV2BindingToV3(binding) {
    if (!isObject(binding)) return null;

    const action = normalizeAction(binding.action);
    if (!action || !validCooldown(binding.cooldownMs)) {
        return null;
    }

    const normalized = cloneJson(binding);
    normalized.tap = action;
    delete normalized.action;
    normalized.cooldownMs = binding.cooldownMs;
    return normalized;
}

function normalizeConfigToV3(config) {
    if (!isObject(config)) throw new Error("configuration root must be an object");

    if (!Object.prototype.hasOwnProperty.call(config, "schemaVersion")) {
        return {
            schemaVersion: RUNTIME_SCHEMA_VERSION,
            contexts: {
                default: {
                    kind: "default",
                    monitors: normalizeMonitorsToV3(config, true),
                },
            },
        };
    }
    if (config.schemaVersion === SCHEMA_VERSION) {
        const normalized = cloneJson(config);
        normalized.schemaVersion = RUNTIME_SCHEMA_VERSION;
        normalized.contexts = {
            default: {
                kind: "default",
                monitors: normalizeMonitorsToV3(config.monitors, false),
            },
        };
        delete normalized.monitors;
        return normalized;
    }
    if (config.schemaVersion !== RUNTIME_SCHEMA_VERSION) {
        throw new Error("unsupported schema version: " + config.schemaVersion);
    }

    const normalized = cloneJson(config);
    normalized.schemaVersion = RUNTIME_SCHEMA_VERSION;
    return normalized;
}

function normalizeMonitorsToV3(monitors, legacy) {
    const normalizedV2 = normalizeMonitors(monitors, legacy);
    const normalized = {};
    for (const outputName of Object.keys(normalizedV2)) {
        const monitor = normalizedV2[outputName];
        if (!isObject(monitor)) {
            continue;
        }
        const normalizedMonitor = {};
        for (const position of Object.keys(monitor)) {
            const binding = normalizeV2BindingToV3(monitor[position]);
            if (!binding) {
                continue;
            }
            normalizedMonitor[position] = binding;
        }
        normalized[outputName] = normalizedMonitor;
    }
    return normalized;
}

function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
}

function clonePlain(value) {
    if (Array.isArray(value)) {
        return value.map(clonePlain);
    }

    if (isObject(value)) {
        const clone = {};
        for (const key of Object.keys(value)) {
            clone[key] = clonePlain(value[key]);
        }
        return clone;
    }

    return value;
}

function classifyAction(action) {
    if (!isObject(action) || typeof action.type !== "string") {
        return "invalid";
    }

    if (action.type === "none") {
        return "none";
    }

    if (action.type === "shortcut") {
        if (typeof action.component === "string" && action.component &&
            typeof action.name === "string" && action.name) {
            return "shortcut";
        }
        return "invalid";
    }

    if (action.type === "command") {
        return validateCommandAction(action).ok ? "command" : "invalid";
    }

    return "invalid";
}

function classifyTapLingerAction(action) {
    if (typeof action === "undefined") {
        return "missing";
    }
    if (!isObject(action)) {
        return "malformed";
    }
    if (action.type === "none") {
        return "none";
    }
    return normalizeAction(action) ? "valid" : "malformed";
}

function isResolvableBinding(binding) {
    return isObject(binding) && classifyAction(binding.tap) !== "invalid";
}

function getContextBinding(context, outputName, position) {
    if (!isObject(context) || !isObject(context.monitors)) {
        return null;
    }
    if (typeof outputName !== "string" || !outputName ||
        typeof position !== "string" || !position) {
        return null;
    }

    if (!hasOwn(context.monitors, outputName)) {
        return null;
    }
    const monitor = context.monitors[outputName];
    if (!isObject(monitor) || !hasOwn(monitor, position)) {
        return null;
    }

    const binding = monitor[position];
    return isObject(binding) ? binding : null;
}

function resolveContextAction(config, contextKey, outputName, position) {
    if (!isObject(config) || !isObject(config.contexts)) {
        return null;
    }
    if (typeof contextKey !== "string" || !contextKey) {
        return null;
    }

    const contexts = config.contexts;
    const defaultContext = hasOwn(contexts, "default") ? contexts.default : null;

    if (contextKey === "default") {
        const binding = getContextBinding(defaultContext, outputName, position);
        if (!isResolvableBinding(binding)) {
            return null;
        }
        return clonePlain(binding);
    }

    const requestedContext = hasOwn(contexts, contextKey) ? contexts[contextKey] : null;
    const exactBinding = getContextBinding(requestedContext, outputName, position);
    if (isResolvableBinding(exactBinding)) {
        return clonePlain(exactBinding);
    }

    const defaultBinding = getContextBinding(defaultContext, outputName, position);
    if (!isResolvableBinding(defaultBinding)) {
        return null;
    }
    return clonePlain(defaultBinding);
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

function createTapLingerState() {
    return {
        active: false,
        enteredAtMs: null,
        lastNowMs: null,
    };
}

function validTapLingerTimestamp(value) {
    return Number.isInteger(value) && value >= 0;
}

function readTapLingerActionStatus(options, key) {
    if (!isObject(options) || !hasOwn(options, key)) {
        return "missing";
    }
    return classifyTapLingerAction(options[key]);
}

function decideTapLinger(state, event, options) {
    if (!isObject(state)) {
        throw new TypeError("state must be an object");
    }
    if (!isObject(event)) {
        throw new TypeError("event must be an object");
    }
    if (typeof event.type !== "string" || !event.type) {
        throw new TypeError("event.type must be a non-empty string");
    }
    if (!validTapLingerTimestamp(event.nowMs)) {
        throw new TypeError("event.nowMs must be a non-negative integer");
    }

    const params = isObject(options) ? options : {};
    const lingerMs = hasOwn(params, "lingerMs") ? params.lingerMs : DEFAULT_LINGER_MS;
    const stayZonePx = hasOwn(params, "stayZonePx") ? params.stayZonePx : DEFAULT_STAY_ZONE_PX;
    if (!validTapLingerTimestamp(lingerMs)) {
        throw new RangeError("lingerMs must be a non-negative integer");
    }
    if (!validTapLingerTimestamp(stayZonePx)) {
        throw new RangeError("stayZonePx must be a non-negative integer");
    }

    const status = {
        tap: readTapLingerActionStatus(params, "tapAction"),
        linger: readTapLingerActionStatus(params, "lingerAction"),
    };
    const tapDispatchable = status.tap === "valid";
    const lingerDispatchable = status.linger === "valid";
    const baseState = Object.assign({}, state, {lastNowMs: event.nowMs});

    function finish(nextState, effects, reason) {
        return {
            state: nextState,
            effects,
            reason,
            status,
        };
    }

    if (state.active === true) {
        if (!validTapLingerTimestamp(state.enteredAtMs) ||
            (state.lastNowMs !== null && !validTapLingerTimestamp(state.lastNowMs))) {
            throw new TypeError("state contains an invalid timestamp");
        }
        if (event.nowMs < (state.lastNowMs === null ? state.enteredAtMs : state.lastNowMs)) {
            return finish(Object.assign({}, state), [], "clock-regression");
        }

        const elapsedMs = event.nowMs - state.enteredAtMs;

        if (event.type === "cancel") {
            return finish(Object.assign({}, baseState, {
                active: false,
                enteredAtMs: null,
            }), [], "cancelled");
        }

        if (event.type === "enter") {
            return finish(baseState, [], "ignored");
        }

        if (elapsedMs >= lingerMs) {
            return finish(Object.assign({}, baseState, {
                active: false,
                enteredAtMs: null,
            }), lingerDispatchable ? ["linger"] : [], lingerDispatchable ? "linger" : "ignored");
        }

        if (event.type === "leave") {
            return finish(Object.assign({}, baseState, {
                active: false,
                enteredAtMs: null,
            }), tapDispatchable ? ["tap"] : [], tapDispatchable ? "tap" : "ignored");
        }

        if (event.type === "move") {
            if (!validTapLingerTimestamp(event.distancePx)) {
                throw new TypeError("event.distancePx must be a non-negative integer");
            }
            if (event.distancePx > stayZonePx) {
                return finish(Object.assign({}, baseState, {
                    active: false,
                    enteredAtMs: null,
                }), tapDispatchable ? ["tap"] : [], tapDispatchable ? "tap" : "ignored");
            }
            return finish(baseState, [], "ignored");
        }

        if (event.type === "tick") {
            return finish(baseState, [], "ignored");
        }

        throw new TypeError("unsupported event type: " + event.type);
    }

    if (event.type === "enter") {
        if (lingerDispatchable) {
            return finish(Object.assign({}, baseState, {
                active: true,
                enteredAtMs: event.nowMs,
            }), [], "pending");
        }
        if (tapDispatchable) {
            return finish(Object.assign({}, baseState, {
                active: false,
                enteredAtMs: null,
            }), ["tap"], "immediate-tap");
        }
        return finish(Object.assign({}, baseState, {
            active: false,
            enteredAtMs: null,
        }), [], "ignored");
    }

    if (event.type === "move" && !validTapLingerTimestamp(event.distancePx)) {
        throw new TypeError("event.distancePx must be a non-negative integer");
    }

    return finish(baseState, [], "ignored");
}

function getCurrentContextKey(screen) {
    const activityId = typeof workspace.currentActivity === "string" ?
        workspace.currentActivity : "";
    let desktopId = "";
    if (workspace && typeof workspace.currentDesktopForScreen === "function") {
        const desktop = workspace.currentDesktopForScreen(screen);
        if (desktop && typeof desktop.id === "string") {
            desktopId = desktop.id;
        }
    } else if (workspace && workspace.currentDesktop &&
               typeof workspace.currentDesktop.id === "string") {
        desktopId = workspace.currentDesktop.id;
    }

    if (activityId && desktopId) {
        return "activity:" + activityId + "|desktop:" + desktopId;
    }
    if (activityId) {
        return "activity:" + activityId;
    }
    if (desktopId) {
        return "desktop:" + desktopId;
    }
    return "default";
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

let runtimeConfig = {schemaVersion: RUNTIME_SCHEMA_VERSION, contexts: {}};
let cooldownTimers = [];
let tapLingerInteractions = [];
let tapLingerSignalsConnected = false;

function loadRuntimeConfig() {
    const raw = readConfig("MonitorConfigs", "{}");
    return normalizeConfigToV3(JSON.parse(raw));
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

function clearAllTapLingerInteractions() {
    for (let i = 0; i < tapLingerInteractions.length; i++) {
        stopTimer(tapLingerInteractions[i].timer);
    }
    tapLingerInteractions = [];
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

function beginTapLingerInteraction(outputName, position, screen, binding, contextKey) {
    if (findTapLingerInteractionIndex(outputName, position) !== -1) {
        return;
    }

    for (let i = tapLingerInteractions.length - 1; i >= 0; i--) {
        const entry = tapLingerInteractions[i];
        if (entry.outputName === outputName && entry.position === position) {
            continue;
        }
        cancelTapLingerInteraction(entry, true);
    }

    const state = createTapLingerState();
    const lingerMs = typeof binding.lingerMs === "number" ? binding.lingerMs : DEFAULT_LINGER_MS;
    const result = decideTapLinger(state, {
        type: "enter",
        nowMs: 0,
    }, {
        tapAction: binding.tap,
        lingerAction: binding.linger,
        lingerMs,
        stayZonePx: DEFAULT_STAY_ZONE_PX,
    });

    if (result.effects.indexOf("tap") !== -1) {
        dispatchResolvedBindingEffect({
            outputName,
            position,
            binding,
            contextKey,
            effect: "tap",
        });
        return;
    }

    if (result.reason !== "pending") {
        return;
    }

    const existingIndex = findTapLingerInteractionIndex(outputName, position);
    if (existingIndex !== -1) {
        cancelTapLingerInteraction(tapLingerInteractions[existingIndex], false);
    }

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

        const interaction = {
            outputName,
            position,
            contextKey,
            binding: cloneJson(binding),
            screenGeometry: cloneJson(screen.geometry),
            state: result.state,
            timer: null,
        };

        timer.timeout.connect(function() {
            handleTapLingerTimeout(interaction);
        });
        timer.start(lingerMs);

        if (!isTimerActive(timer)) {
            throw new Error("timer is not active after start");
        }

        interaction.timer = timer;
        tapLingerInteractions.push(interaction);
    } catch (e) {
        stopTimer(timer);
        print("hotcorners-per-monitor: failed to start linger timer:", e);
    }
}

function findTapLingerInteractionIndex(outputName, position) {
    for (let i = 0; i < tapLingerInteractions.length; i++) {
        const entry = tapLingerInteractions[i];
        if (entry.outputName === outputName && entry.position === position) {
            return i;
        }
    }
    return -1;
}

function removeTapLingerInteraction(outputName, position, timer) {
    for (let i = 0; i < tapLingerInteractions.length; i++) {
        const entry = tapLingerInteractions[i];
        if (entry.outputName !== outputName || entry.position !== position) {
            continue;
        }
        if (timer && entry.timer !== timer) {
            continue;
        }
        tapLingerInteractions.splice(i, 1);
        return entry;
    }
    return null;
}

function getTapLingerCursorPos() {
    if (!workspace || !workspace.cursorPos) {
        return null;
    }
    const cursor = workspace.cursorPos;
    if (typeof cursor.x !== "number" || typeof cursor.y !== "number") {
        return null;
    }
    return cursor;
}

function isCursorInTapLingerStayZone(cursorPos, geometry, position) {
    if (!cursorPos || !geometry || typeof position !== "string") {
        return false;
    }

    const left = geometry.x;
    const top = geometry.y;
    const right = geometry.x + geometry.width;
    const bottom = geometry.y + geometry.height;
    const x = cursorPos.x;
    const y = cursorPos.y;

    if (position === "TopLeft") {
        return x >= left && x <= left + DEFAULT_STAY_ZONE_PX &&
               y >= top && y <= top + DEFAULT_STAY_ZONE_PX;
    }
    if (position === "TopRight") {
        return x <= right && x >= right - DEFAULT_STAY_ZONE_PX &&
               y >= top && y <= top + DEFAULT_STAY_ZONE_PX;
    }
    if (position === "BottomLeft") {
        return x >= left && x <= left + DEFAULT_STAY_ZONE_PX &&
               y <= bottom && y >= bottom - DEFAULT_STAY_ZONE_PX;
    }
    if (position === "BottomRight") {
        return x <= right && x >= right - DEFAULT_STAY_ZONE_PX &&
               y <= bottom && y >= bottom - DEFAULT_STAY_ZONE_PX;
    }
    if (position === "Top") {
        return y >= top && y <= top + DEFAULT_STAY_ZONE_PX &&
               x >= left && x <= right;
    }
    if (position === "Bottom") {
        return y <= bottom && y >= bottom - DEFAULT_STAY_ZONE_PX &&
               x >= left && x <= right;
    }
    if (position === "Left") {
        return x >= left && x <= left + DEFAULT_STAY_ZONE_PX &&
               y >= top && y <= bottom;
    }
    if (position === "Right") {
        return x <= right && x >= right - DEFAULT_STAY_ZONE_PX &&
               y >= top && y <= bottom;
    }

    return false;
}

function dispatchResolvedBindingEffect(entry, effect) {
    const action = effect === "linger" ? entry.binding.linger : entry.binding.tap;
    if (!isDispatchableAction(action)) {
        return;
    }
    if (!dispatchActionThroughCooldown(entry.outputName, entry.position, entry.binding.cooldownMs, action)) {
        return;
    }
}

function dispatchActionThroughCooldown(outputName, position, cooldownMs, action) {
    if (!isDispatchableAction(action)) {
        return false;
    }
    if (!validCooldown(cooldownMs)) {
        return false;
    }

    if (cooldownMs > 0) {
        if (isCooldownActive(outputName, position)) {
            return false;
        }
        if (!beginCooldown(outputName, position, cooldownMs)) {
            return false;
        }
    }

    try {
        executeAction(action);
        return true;
    } catch (e) {
        print("hotcorners-per-monitor: failed to invoke action:", e);
        return false;
    }
}

function cancelTapLingerInteraction(entry, dispatchTap) {
    if (!entry) {
        return;
    }

    stopTimer(entry.timer);
    removeTapLingerInteraction(entry.outputName, entry.position, entry.timer);

    if (!dispatchTap) {
        return;
    }

    dispatchResolvedBindingEffect(entry, "tap");
}

function handleTapLingerTimeout(entry) {
    const index = findTapLingerInteractionIndex(entry.outputName, entry.position);
    if (index === -1 || tapLingerInteractions[index] !== entry) {
        return;
    }

    removeTapLingerInteraction(entry.outputName, entry.position, entry.timer);
    stopTimer(entry.timer);

    const result = decideTapLinger(entry.state, {
        type: "tick",
        nowMs: typeof entry.binding.lingerMs === "number" ? entry.binding.lingerMs : DEFAULT_LINGER_MS,
    }, {
        tapAction: entry.binding.tap,
        lingerAction: entry.binding.linger,
        lingerMs: typeof entry.binding.lingerMs === "number" ? entry.binding.lingerMs : DEFAULT_LINGER_MS,
        stayZonePx: DEFAULT_STAY_ZONE_PX,
    });

    if (result.effects.indexOf("linger") === -1) {
        return;
    }

    dispatchResolvedBindingEffect(entry, "linger");
}

function handleTapLingerCursorChange() {
    const cursorPos = getTapLingerCursorPos();
    if (!cursorPos) {
        clearAllTapLingerInteractions();
        return;
    }

    for (let i = tapLingerInteractions.length - 1; i >= 0; i--) {
        const entry = tapLingerInteractions[i];
        if (!isCursorInTapLingerStayZone(cursorPos, entry.screenGeometry, entry.position)) {
            cancelTapLingerInteraction(entry, true);
        }
    }
}

function connectTapLingerSignals() {
    if (tapLingerSignalsConnected) {
        return;
    }
    tapLingerSignalsConnected = true;

    if (workspace && workspace.cursorPosChanged &&
        typeof workspace.cursorPosChanged.connect === "function") {
        workspace.cursorPosChanged.connect(handleTapLingerCursorChange);
    }

    if (workspace && workspace.screensChanged &&
        typeof workspace.screensChanged.connect === "function") {
        workspace.screensChanged.connect(function() {
            clearAllTapLingerInteractions();
        });
    }
}

function loadConfig() {
    clearAllCooldownTimers();
    clearAllTapLingerInteractions();
    try {
        runtimeConfig = loadRuntimeConfig();
        print("hotcorners-per-monitor: config loaded for outputs:",
              Object.keys(runtimeConfig.contexts || {}).join(", ") || "(none)");
    } catch (e) {
        print("hotcorners-per-monitor: failed to load config:", e);
        runtimeConfig = {schemaVersion: RUNTIME_SCHEMA_VERSION, contexts: {}};
    }
}

function cleanupRuntime() {
    clearAllCooldownTimers();
    clearAllTapLingerInteractions();
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

    const contextKey = getCurrentContextKey(screen);
    const binding = resolveContextAction(runtimeConfig, contextKey, outputName, positionName);
    if (!binding) return;

    beginTapLingerInteraction(outputName, positionName, screen, binding, contextKey);
}

// Bootstrap: load config + register all 8 corners/edges
loadConfig();
connectTapLingerSignals();

for (const positionName of Object.keys(POSITIONS)) {
    const border = POSITIONS[positionName];
    registerScreenEdge(border, function() {
        handleCorner(positionName);
    });
}
