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

function createBackend(config = legacyConfig) {
    const callbacks = new Map();
    const dbusCalls = [];
    const prints = [];
    const writes = [];
    const rawConfig = typeof config === "string"
        ? config
        : JSON.stringify(config);
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
        callDBus(...args) {
            dbusCalls.push(args);
        },
        print(...args) {
            prints.push(args);
        },
    });

    vm.runInContext(backendSource, context, {filename: BACKEND_PATH});
    return {callbacks, context, dbusCalls, prints, workspace, writes};
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

test("runtime load migrates v0.1 to v0.2 in memory without writing", () => {
    const backend = createBackend(legacyConfig);

    const config = plain(backend.context.loadRuntimeConfig());

    assert.equal(config.schemaVersion, 2);
    assert.equal(config.monitors["DP-1"].TopLeft.cooldownMs, 0);
    assert.deepEqual(backend.writes, []);
});

test("dispatches a shortcut from normalized v0.2 config without writing", () => {
    const backend = createBackend(v2Config);
    backend.workspace.cursorPos = {x: 3500, y: 10};

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopRight)();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.dbusCalls[0][4], "Lock Session");
    assert.deepEqual(backend.writes, []);
});

test("does not apply v0.2 cooldown during runtime dispatch yet", () => {
    const config = structuredClone(v2Config);
    config.monitors["DP-1"].TopLeft.cooldownMs = 350;
    const backend = createBackend(config);
    let cooldownCalls = 0;
    backend.context.decideCooldown = () => {
        cooldownCalls++;
        throw new Error("cooldown must remain disconnected");
    };

    const callback = backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft);
    callback();
    callback();

    assert.equal(backend.dbusCalls.length, 2);
    assert.equal(cooldownCalls, 0);
});

test("does not dispatch explicit none from normalized v0.2 config", () => {
    const backend = createBackend(v2Config);
    const config = plain(backend.context.loadRuntimeConfig());

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricBottomRight)();

    assert.equal(config.monitors["DP-1"].BottomRight.action.type, "none");
    assert.deepEqual(backend.dbusCalls, []);
});

test("unsupported schema version fails closed without writing", () => {
    const backend = createBackend({schemaVersion: 99, monitors: {}});

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft)();

    assert.deepEqual(backend.dbusCalls, []);
    assert.deepEqual(backend.writes, []);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("failed to load config")),
        true,
    );
});

test("invalid JSON fails closed without writing or partial dispatch", () => {
    const backend = createBackend('{"DP-1":{"TopLeft":');

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft)();

    assert.deepEqual(backend.dbusCalls, []);
    assert.deepEqual(backend.writes, []);
    assert.equal(
        backend.prints.some(args => args.join(" ").includes("failed to load config")),
        true,
    );
});

test("invalid known binding is removed and cannot dispatch", () => {
    const invalidConfig = structuredClone(v2Config);
    invalidConfig.monitors["DP-1"].TopLeft.action.name = "";
    const backend = createBackend(invalidConfig);
    const config = plain(backend.context.loadRuntimeConfig());

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft)();

    assert.equal(Object.hasOwn(config.monitors["DP-1"], "TopLeft"), false);
    assert.deepEqual(backend.dbusCalls, []);
});

test("unknown v0.2 fields do not affect known shortcut dispatch", () => {
    const backend = createBackend(extensionConfig);

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft)();

    assert.equal(backend.dbusCalls.length, 1);
    assert.equal(backend.dbusCalls[0][4], "Overview");
});

test("runtime normalization and dispatch do not mutate input fixtures", () => {
    const input = structuredClone(extensionConfig);
    const original = structuredClone(input);
    const backend = createBackend(input);

    backend.callbacks.get(ELECTRIC_BORDERS.ElectricTopLeft)();
    backend.context.loadRuntimeConfig();

    assert.deepEqual(input, original);
});
