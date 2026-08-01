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

let monitorConfigs = {};

function loadConfig() {
    const raw = readConfig("MonitorConfigs", "{}");
    try {
        monitorConfigs = JSON.parse(raw);
        print("hotcorners-per-monitor: config loaded for outputs:",
              Object.keys(monitorConfigs).join(", ") || "(none)");
    } catch (e) {
        print("hotcorners-per-monitor: failed to parse config:", e);
        monitorConfigs = {};
    }
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

function executeAction(action) {
    if (!action || !action.type || action.type === "none") {
        return;
    }
    if (action.type === "shortcut") {
        const component = action.component || "kwin";
        const name = action.name;
        if (!name) return;
        callDBus(
            "org.kde.kglobalaccel",
            "/component/" + component,
            "org.kde.kglobalaccel.Component",
            "invokeShortcut",
            name
        );
        return;
    }
    print("hotcorners-per-monitor: unknown action type:", action.type);
}

function handleCorner(positionName) {
    const screen = getScreenAtCursor();
    if (!screen) return;
    const screenName = screen.name;
    if (!screenName) return;
    const screenConfig = monitorConfigs[screenName];
    if (!screenConfig) return;
    const action = screenConfig[positionName];
    if (!action) return;
    executeAction(action);
}

// Bootstrap: load config + register all 8 corners/edges
loadConfig();

for (const positionName of Object.keys(POSITIONS)) {
    const border = POSITIONS[positionName];
    registerScreenEdge(border, function() {
        handleCorner(positionName);
    });
}
