const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

// specs/CONFIG_SCHEMA.md: "Precedence is combined activity+desktop, activity,
// desktop, default" and "Within the ordered context precedence, the first
// context that contains the output/position binding wins." These tests cover
// the full four-tier cascade; context-fallback.test.js covers the single-key
// resolveContextAction primitive that each tier is built from.

function loadBackend() {
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

function loadCascadeResolver() {
    return loadBackend().resolveContextActionCascade;
}

const ACTIVITY = "act-1";
const DESKTOP = "desk-1";

function shortcut(name) {
    return {type: "shortcut", component: "kwin", name};
}

function none() {
    return {type: "none"};
}

function binding(tap, extra = {}) {
    return Object.assign({tap}, extra);
}

function context(kind, monitors = {}, extra = {}) {
    return Object.assign({kind, monitors}, extra);
}

function tieredConfig({combined, activity, desktop, byDefault} = {}) {
    const contexts = {};
    if (byDefault !== undefined) {
        contexts.default = context("default", {"DP-1": {TopLeft: byDefault}});
    }
    if (combined !== undefined) {
        contexts[`activity:${ACTIVITY}|desktop:${DESKTOP}`] = context(
            "activityDesktop",
            {"DP-1": {TopLeft: combined}},
            {activityId: ACTIVITY, desktopId: DESKTOP},
        );
    }
    if (activity !== undefined) {
        contexts[`activity:${ACTIVITY}`] = context(
            "activity",
            {"DP-1": {TopLeft: activity}},
            {activityId: ACTIVITY},
        );
    }
    if (desktop !== undefined) {
        contexts[`desktop:${DESKTOP}`] = context(
            "desktop",
            {"DP-1": {TopLeft: desktop}},
            {desktopId: DESKTOP},
        );
    }
    return {schemaVersion: 3, contexts};
}

function resolve(resolver, config, {
    activityId = ACTIVITY,
    desktopId = DESKTOP,
    outputName = "DP-1",
    position = "TopLeft",
} = {}) {
    return resolver(config, activityId, desktopId, outputName, position);
}

function tapName(result) {
    return result && result.tap ? result.tap.name : null;
}

test("cascade resolver function is exposed by the backend script", () => {
    assert.equal(typeof loadCascadeResolver(), "function");
});

test("tier 1: combined activity+desktop wins over all lower tiers", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        combined: binding(shortcut("Combined")),
        activity: binding(shortcut("Activity")),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config)), "Combined");
});

test("tier 2: activity-only wins when combined context is absent", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        activity: binding(shortcut("Activity")),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config)), "Activity");
});

test("tier 3: desktop-only wins when combined and activity contexts are absent", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config)), "Desktop");
});

test("tier 4: default is used when no override tier matches", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({byDefault: binding(shortcut("Default"))});

    assert.equal(tapName(resolve(resolver, config)), "Default");
});

test("activity-only override applies while a desktop is also active", () => {
    // The regression that motivated this cascade: with both an activity and a
    // desktop active, the runtime previously computed only the combined key,
    // so an activity-only context could never match.
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        activity: binding(shortcut("Activity")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config)), "Activity");
});

test("desktop-only override applies while an activity is also active", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config)), "Desktop");
});

test("explicit none in a higher tier blocks fallback to lower tiers", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        combined: binding(none()),
        activity: binding(shortcut("Activity")),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    const result = resolve(resolver, config);
    assert.equal(result.tap.type, "none");
});

test("explicit none in the activity tier blocks the desktop and default tiers", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        activity: binding(none()),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(resolve(resolver, config).tap.type, "none");
});

test("a missing binding continues to the next tier instead of blocking", () => {
    const resolver = loadCascadeResolver();
    // Combined context exists but has no binding for this output/position.
    const config = tieredConfig({
        activity: binding(shortcut("Activity")),
        byDefault: binding(shortcut("Default")),
    });
    config.contexts[`activity:${ACTIVITY}|desktop:${DESKTOP}`] = context(
        "activityDesktop", {}, {activityId: ACTIVITY, desktopId: DESKTOP},
    );

    assert.equal(tapName(resolve(resolver, config)), "Activity");
});

test("no active activity skips the activity tiers and uses desktop", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        activity: binding(shortcut("Activity")),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config, {activityId: ""})), "Desktop");
});

test("no active desktop skips the desktop tier and uses activity", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        activity: binding(shortcut("Activity")),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config, {desktopId: ""})), "Activity");
});

test("neither activity nor desktop active resolves only the default context", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        combined: binding(shortcut("Combined")),
        activity: binding(shortcut("Activity")),
        desktop: binding(shortcut("Desktop")),
        byDefault: binding(shortcut("Default")),
    });

    const result = resolve(resolver, config, {activityId: "", desktopId: ""});
    assert.equal(tapName(result), "Default");
});

test("malformed binding in a higher tier fails closed and continues the cascade", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        combined: binding({type: "shortcut", component: "kwin"}), // no name
        activity: binding(shortcut("Activity")),
        byDefault: binding(shortcut("Default")),
    });

    assert.equal(tapName(resolve(resolver, config)), "Activity");
});

test("malformed entries in every tier resolve to null", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({
        combined: binding({type: "shortcut", component: "kwin"}),
        activity: binding({type: "bogus"}),
        desktop: binding({type: "shortcut", name: "NoComponent"}),
        byDefault: binding({type: "command", program: ""}),
    });

    assert.equal(resolve(resolver, config), null);
});

test("missing contexts.default with no matching tier resolves to null", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({});

    assert.equal(resolve(resolver, config), null);
});

test("cascade does not inherit across outputs or positions", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({activity: binding(shortcut("Activity"))});

    assert.equal(resolve(resolver, config, {outputName: "HDMI-A-1"}), null);
    assert.equal(resolve(resolver, config, {position: "TopRight"}), null);
});

test("cascade returns defensive copies and does not mutate its input", () => {
    const resolver = loadCascadeResolver();
    const config = tieredConfig({activity: binding(shortcut("Activity"))});
    const before = JSON.parse(JSON.stringify(config));

    const result = resolve(resolver, config);
    result.tap.name = "Mutated";

    assert.deepEqual(config, before);
});

// Arrays built inside the VM realm are not reference-equal to host arrays,
// so compare their plain JSON projection (same approach as backend.test.js).
function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

test("cascade key order is combined, then activity, then desktop", () => {
    const backendContext = loadBackend();
    assert.equal(typeof backendContext.buildContextCascadeKeys, "function");

    const keys = backendContext.buildContextCascadeKeys(ACTIVITY, DESKTOP);
    assert.deepEqual(plain(keys), [
        `activity:${ACTIVITY}|desktop:${DESKTOP}`,
        `activity:${ACTIVITY}`,
        `desktop:${DESKTOP}`,
    ]);
});

test("cascade key order omits tiers whose identifier is absent", () => {
    const backendContext = loadBackend();
    const build = backendContext.buildContextCascadeKeys;

    assert.deepEqual(plain(build(ACTIVITY, "")), [`activity:${ACTIVITY}`]);
    assert.deepEqual(plain(build("", DESKTOP)), [`desktop:${DESKTOP}`]);
    assert.deepEqual(plain(build("", "")), []);
});
