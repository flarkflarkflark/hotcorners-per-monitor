const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");
const legacyConfig = readFixture("v0.1-config.json");
const expectedConfig = readFixture("v0.2-migrated-config.json");
const extensionConfig = readFixture("v0.2-config-with-extensions.json");
const actions = readFixture("v0.1-actions.json");

function readFixture(name) {
    return JSON.parse(
        fs.readFileSync(path.join(ROOT, "tests/fixtures", name), "utf8"),
    );
}

function loadSchemaFunctions() {
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
    return context;
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

test("migrates the v0.1 fixture to the normative v0.2 fixture", () => {
    const schema = loadSchemaFunctions();

    assert.deepEqual(
        plain(schema.normalizeConfigToV2(legacyConfig)),
        expectedConfig,
    );
});

test("v0.1 migration does not mutate its input", () => {
    const schema = loadSchemaFunctions();
    const original = structuredClone(legacyConfig);

    schema.normalizeConfigToV2(legacyConfig);

    assert.deepEqual(legacyConfig, original);
});

test("new v0.2 bindings default to a 350 ms cooldown", () => {
    const schema = loadSchemaFunctions();

    assert.deepEqual(
        plain(schema.createV2Binding(actions.builtinShortcut)),
        {action: actions.builtinShortcut, cooldownMs: 350},
    );
});

test("normalizing the v0.2 fixture is idempotent", () => {
    const schema = loadSchemaFunctions();

    assert.deepEqual(
        plain(schema.normalizeConfigToV2(expectedConfig)),
        expectedConfig,
    );
});

test("preserves unknown v0.2 fields without mutating extensions", () => {
    const schema = loadSchemaFunctions();
    const original = structuredClone(extensionConfig);

    const normalized = plain(schema.normalizeConfigToV2(extensionConfig));

    assert.deepEqual(normalized, original);
    normalized.xTestRootTypes.object.nested = "changed";
    normalized.monitors["DP-1"].xTestMonitorMetadata.flags.push(true);
    assert.deepEqual(extensionConfig, original);
});
