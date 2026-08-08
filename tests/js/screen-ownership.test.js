const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

function loadGetScreenAtCursor() {
    const context = vm.createContext({
        KWin: {
            ElectricTopLeft: 0,
            ElectricTop: 1,
            ElectricTopRight: 2,
            ElectricRight: 3,
            ElectricBottomRight: 4,
            ElectricBottom: 5,
            ElectricBottomLeft: 6,
            ElectricLeft: 7,
        },
        workspace: {cursorPos: {x: 0, y: 0}, screens: []},
        readConfig() { return "{}"; },
        registerScreenEdge() { return true; },
        callDBus() {},
        print() {},
    });
    vm.runInContext(backendSource, context, {filename: BACKEND_PATH});
    return {context, workspace: context.workspace, getScreenAtCursor: context.getScreenAtCursor};
}

test("ordinary matching output is returned", () => {
    const {workspace, getScreenAtCursor} = loadGetScreenAtCursor();
    workspace.screens = [
        {name: "DP-1", geometry: {x: 0, y: 0, width: 1920, height: 1080}},
        {name: "HDMI-A-1", geometry: {x: 1920, y: 0, width: 1920, height: 1080}},
    ];
    workspace.cursorPos = {x: 10, y: 10};

    const screen = getScreenAtCursor();

    assert.equal(screen && screen.name, "DP-1");
});

test("zero matches fails closed with null", () => {
    const {workspace, getScreenAtCursor} = loadGetScreenAtCursor();
    workspace.screens = [
        {name: "DP-1", geometry: {x: 0, y: 0, width: 1920, height: 1080}},
    ];
    workspace.cursorPos = {x: 5000, y: 5000};

    assert.equal(getScreenAtCursor(), null);
});

test("two overlapping outputs fail closed with null", () => {
    const {workspace, getScreenAtCursor} = loadGetScreenAtCursor();
    workspace.screens = [
        {name: "DP-1", geometry: {x: 0, y: 0, width: 1920, height: 1080}},
        {name: "DP-2", geometry: {x: 1000, y: 0, width: 1920, height: 1080}},
    ];
    // x=1500 falls inside both DP-1 (0..1920) and DP-2 (1000..2920).
    workspace.cursorPos = {x: 1500, y: 10};

    assert.equal(getScreenAtCursor(), null);
});

test("cloned identical geometries fail closed with null", () => {
    const {workspace, getScreenAtCursor} = loadGetScreenAtCursor();
    workspace.screens = [
        {name: "DP-1", geometry: {x: 0, y: 0, width: 1920, height: 1080}},
        {name: "DP-1-clone", geometry: {x: 0, y: 0, width: 1920, height: 1080}},
    ];
    workspace.cursorPos = {x: 10, y: 10};

    assert.equal(getScreenAtCursor(), null);
});

test("adjacent outputs at a shared half-open boundary resolve to exactly one owner", () => {
    const {workspace, getScreenAtCursor} = loadGetScreenAtCursor();
    workspace.screens = [
        {name: "DP-1", geometry: {x: 0, y: 0, width: 1920, height: 1080}},
        {name: "HDMI-A-1", geometry: {x: 1920, y: 0, width: 1920, height: 1080}},
    ];

    // The shared boundary column (x=1920) belongs to the right-hand
    // screen only: DP-1 spans [0, 1920), HDMI-A-1 spans [1920, 3840).
    workspace.cursorPos = {x: 1919, y: 10};
    assert.equal(getScreenAtCursor().name, "DP-1");

    workspace.cursorPos = {x: 1920, y: 10};
    assert.equal(getScreenAtCursor().name, "HDMI-A-1");
});
