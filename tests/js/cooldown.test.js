const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

function loadCooldownFunction() {
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
    return context.decideCooldown;
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

function trigger(decide, state, {
    outputName = "HDMI-A-1",
    position = "TopLeft",
    cooldownMs = 350,
    nowMs,
}) {
    return decide(state, outputName, position, cooldownMs, nowMs);
}

test("first trigger at timestamp zero is allowed and stored", () => {
    const decide = loadCooldownFunction();
    const state = {entries: []};

    const result = trigger(decide, state, {nowMs: 0});

    assert.equal(result.allowed, true);
    assert.equal(result.reason, "first-trigger");
    assert.deepEqual(plain(result.state), {
        entries: [{
            outputName: "HDMI-A-1",
            position: "TopLeft",
            lastTriggeredMs: 0,
        }],
    });
});

test("trigger inside cooldown is denied without moving timestamp", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {nowMs: 1200});

    assert.equal(result.allowed, false);
    assert.equal(result.reason, "cooldown-active");
    assert.equal(plain(result.state).entries[0].lastTriggeredMs, 1000);
});

test("trigger one millisecond before boundary is denied", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {nowMs: 1349});

    assert.equal(result.allowed, false);
    assert.equal(result.reason, "cooldown-active");
});

test("trigger exactly on cooldown boundary is allowed", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {nowMs: 1350});

    assert.equal(result.allowed, true);
    assert.equal(result.reason, "cooldown-elapsed");
    assert.equal(plain(result.state).entries[0].lastTriggeredMs, 1350);
});

test("trigger after cooldown boundary is allowed and stored", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {nowMs: 2000});

    assert.equal(result.allowed, true);
    assert.equal(result.reason, "cooldown-elapsed");
    assert.equal(plain(result.state).entries[0].lastTriggeredMs, 2000);
});

test("allowed retrigger replaces its existing output and position entry", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {nowMs: 1350});
    const entries = plain(result.state).entries;

    assert.equal(entries.length, 1);
    assert.equal(entries[0].lastTriggeredMs, 1350);
});

test("denied trigger does not shift the cooldown deadline", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});
    const denied = trigger(decide, first.state, {nowMs: 1200});

    const boundary = trigger(decide, denied.state, {nowMs: 1350});

    assert.equal(boundary.allowed, true);
    assert.equal(plain(boundary.state).entries[0].lastTriggeredMs, 1350);
});

test("zero cooldown allows repeated triggers at identical timestamp", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 0, cooldownMs: 0});
    const second = trigger(decide, first.state, {nowMs: 0, cooldownMs: 0});
    const third = trigger(decide, second.state, {nowMs: 0, cooldownMs: 0});

    assert.equal(first.allowed, true);
    assert.equal(second.allowed, true);
    assert.equal(third.allowed, true);
    assert.equal(plain(third.state).entries[0].lastTriggeredMs, 0);
});

test("same position on different outputs has independent cooldown", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {
        outputName: "DP-1",
        position: "TopLeft",
        nowMs: 1000,
    });

    assert.equal(result.allowed, true);
    assert.equal(plain(result.state).entries.length, 2);
});

test("different positions on same output have independent cooldown", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});

    const result = trigger(decide, first.state, {
        position: "TopRight",
        nowMs: 1000,
    });

    assert.equal(result.allowed, true);
    assert.equal(plain(result.state).entries.length, 2);
});

test("separator characters in output and position cannot collide", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {
        outputName: "a:b",
        position: "c",
        nowMs: 1000,
    });

    const result = trigger(decide, first.state, {
        outputName: "a",
        position: "b:c",
        nowMs: 1000,
    });

    assert.equal(result.allowed, true);
    assert.equal(plain(result.state).entries.length, 2);
});

test("decision never mutates input state", () => {
    const decide = loadCooldownFunction();
    const state = {
        entries: [{
            outputName: "HDMI-A-1",
            position: "TopLeft",
            lastTriggeredMs: 1000,
        }],
    };
    const original = structuredClone(state);
    Object.freeze(state.entries[0]);
    Object.freeze(state.entries);
    Object.freeze(state);

    const allowed = trigger(decide, state, {nowMs: 1350});
    const denied = trigger(decide, state, {nowMs: 1200});

    assert.deepEqual(state, original);
    assert.notEqual(allowed.state, state);
    assert.equal(denied.state, state);
});

test("clock regression is denied without state mutation", () => {
    const decide = loadCooldownFunction();
    const first = trigger(decide, {entries: []}, {nowMs: 1000});
    const before = plain(first.state);

    const result = trigger(decide, first.state, {nowMs: 999});

    assert.equal(result.allowed, false);
    assert.equal(result.reason, "clock-regression");
    assert.deepEqual(plain(result.state), before);
});

test("invalid cooldown values throw without mutating state", () => {
    const decide = loadCooldownFunction();
    const invalidValues = [-1, 1.5, NaN, Infinity];

    for (const cooldownMs of invalidValues) {
        const state = {entries: []};
        assert.throws(
            () => trigger(decide, state, {nowMs: 0, cooldownMs}),
            /cooldownMs/,
        );
        assert.deepEqual(state, {entries: []});
    }
});

test("invalid timestamp and empty key values throw", () => {
    const decide = loadCooldownFunction();
    const state = {entries: []};

    for (const nowMs of [-1, NaN, Infinity]) {
        assert.throws(() => trigger(decide, state, {nowMs}), /nowMs/);
    }
    assert.throws(
        () => trigger(decide, state, {outputName: "", nowMs: 0}),
        /outputName/,
    );
    assert.throws(
        () => trigger(decide, state, {position: "", nowMs: 0}),
        /position/,
    );
    assert.deepEqual(state, {entries: []});
});
