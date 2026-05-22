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
