const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const FIXTURE_PATH = path.join(ROOT, "tests/fixtures/v0.1-config.json");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");
const legacyConfig = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

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

function createBackend(config = legacyConfig) {
    const callbacks = new Map();
    const dbusCalls = [];
    const prints = [];
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
    const context = vm.createContext({
        KWin: ELECTRIC_BORDERS,
        workspace,
        readConfig(key, fallback) {
            assert.equal(key, "MonitorConfigs");
            return config === undefined ? fallback : JSON.stringify(config);
        },
        registerScreenEdge(border, callback) {
            callbacks.set(border, callback);
            return true;
        },
        callDBus(...args) {
            dbusCalls.push(args);
        },
        print(...args) {
            prints.push(args);
        },
    });

    vm.runInContext(backendSource, context, {filename: BACKEND_PATH});
    return {callbacks, dbusCalls, prints, workspace};
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

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft)();

    assert.deepEqual(backend.dbusCalls, [[
        "org.kde.kglobalaccel",
        "/component/kwin",
        "org.kde.kglobalaccel.Component",
        "invokeShortcut",
        "Overview",
    ]]);
});

test("selects the matching monitor before dispatching a legacy shortcut", () => {
    const backend = createBackend();
    backend.workspace.cursorPos = {x: 3500, y: 10};

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopRight)();

    assert.deepEqual(backend.dbusCalls, [[
        "org.kde.kglobalaccel",
        "/component/ksmserver",
        "org.kde.kglobalaccel.Component",
        "invokeShortcut",
        "Lock Session",
    ]]);
});

test("does not dispatch a legacy none action", () => {
    const backend = createBackend();
    backend.workspace.cursorPos = {x: 100, y: 100};

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricBottomRight)();

    assert.deepEqual(backend.dbusCalls, []);
});
