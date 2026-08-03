const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

function loadTapLingerHelpers() {
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
        workspace: {cursorPos: {x: 0, y: 0}, screens: [], currentActivity: "", currentDesktopForScreen() { return null; }},
        readConfig() { return "{}"; },
        registerScreenEdge() { return true; },
        callDBus() {},
        print() {},
    });
    vm.runInContext(backendSource, context, {filename: BACKEND_PATH});
    return {
        createTapLingerState: context.createTapLingerState,
        decideTapLinger: context.decideTapLinger,
    };
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

function shortcut(name) {
    return {type: "shortcut", component: "kwin", name};
}

function command(program = "/usr/bin/printf", arguments_ = ["hello"]) {
    return {type: "command", program, arguments: arguments_};
}

function none() {
    return {type: "none"};
}

function malformedShortcut() {
    return {type: "shortcut", component: "", name: ""};
}

function makeOptions(extra = {}) {
    return Object.assign({
        tapAction: shortcut("Overview"),
        lingerAction: shortcut("Show Desktop"),
        lingerMs: 500,
        stayZonePx: 8,
    }, extra);
}

function enter(nowMs = 0, extra = {}) {
    return Object.assign({type: "enter", nowMs}, extra);
}

function move(nowMs, distancePx, extra = {}) {
    return Object.assign({type: "move", nowMs, distancePx}, extra);
}

function tick(nowMs, extra = {}) {
    return Object.assign({type: "tick", nowMs}, extra);
}

function leave(nowMs, extra = {}) {
    return Object.assign({type: "leave", nowMs}, extra);
}

function cancel(nowMs, extra = {}) {
    return Object.assign({type: "cancel", nowMs}, extra);
}

function run(decide, state, event, options = {}) {
    return decide(state, event, options);
}

test("helper functions are exposed", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    assert.equal(typeof createTapLingerState, "function");
    assert.equal(typeof decideTapLinger, "function");
});

test("initial state is idle", () => {
    const {createTapLingerState} = loadTapLingerHelpers();
    assert.deepEqual(plain(createTapLingerState()), {
        active: false,
        enteredAtMs: null,
        lastNowMs: null,
    });
});

test("enter with linger action starts a pending interaction", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const state = createTapLingerState();

    const result = run(decideTapLinger, state, enter(1000), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "pending");
    assert.deepEqual(plain(result.state), {
        active: true,
        enteredAtMs: 1000,
        lastNowMs: 1000,
    });
});

test("leave before threshold produces tap", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());

    const result = run(decideTapLinger, first.state, leave(1200), makeOptions());

    assert.deepEqual(plain(result.effects), ["tap"]);
    assert.equal(result.reason, "tap");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1200,
    });
});

test("move at exactly 8 px stays inside the stay zone", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());

    const result = run(decideTapLinger, first.state, move(1200, 8), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: true,
        enteredAtMs: 1000,
        lastNowMs: 1200,
    });
});

test("move beyond 8 px before threshold produces tap", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());

    const result = run(decideTapLinger, first.state, move(1200, 9), makeOptions());

    assert.deepEqual(plain(result.effects), ["tap"]);
    assert.equal(result.reason, "tap");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1200,
    });
});

test("exact 500 ms tick produces linger", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());

    const result = run(decideTapLinger, first.state, tick(1500), makeOptions());

    assert.deepEqual(plain(result.effects), ["linger"]);
    assert.equal(result.reason, "linger");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1500,
    });
});

test("linger suppresses later tap and repeated ticks stay silent", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const linger = run(decideTapLinger, first.state, tick(1500), makeOptions());

    const laterTap = run(decideTapLinger, linger.state, leave(1600), makeOptions());
    const repeatedTick = run(decideTapLinger, linger.state, tick(1600), makeOptions());

    assert.deepEqual(plain(laterTap.effects), []);
    assert.equal(laterTap.reason, "ignored");
    assert.deepEqual(plain(repeatedTick.effects), []);
    assert.equal(repeatedTick.reason, "ignored");
});

test("leave after linger produces nothing", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const linger = run(decideTapLinger, first.state, tick(1500), makeOptions());

    const result = run(decideTapLinger, linger.state, leave(1600), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1600,
    });
});

test("cancel before threshold produces nothing", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());

    const result = run(decideTapLinger, first.state, cancel(1200), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "cancelled");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1200,
    });
});

test("cancel after linger produces nothing extra", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const linger = run(decideTapLinger, first.state, tick(1500), makeOptions());

    const result = run(decideTapLinger, linger.state, cancel(1600), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1600,
    });
});

test("no linger action preserves immediate tap", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(
        decideTapLinger,
        createTapLingerState(),
        enter(1000),
        makeOptions({lingerAction: undefined, tapAction: command()}),
    );

    assert.deepEqual(plain(result.effects), ["tap"]);
    assert.equal(result.reason, "immediate-tap");
    assert.deepEqual(plain(result.status), {
        tap: "valid",
        linger: "missing",
    });
});

test("tap action none produces no action", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(
        decideTapLinger,
        createTapLingerState(),
        enter(1000),
        makeOptions({tapAction: none(), lingerAction: undefined}),
    );

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.status), {
        tap: "none",
        linger: "missing",
    });
});

test("linger action none behaves like no linger and does not suppress immediate tap", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(
        decideTapLinger,
        createTapLingerState(),
        enter(1000),
        makeOptions({lingerAction: none()}),
    );

    assert.deepEqual(plain(result.effects), ["tap"]);
    assert.equal(result.reason, "immediate-tap");
    assert.deepEqual(plain(result.status), {
        tap: "valid",
        linger: "none",
    });
});

test("malformed tap action does not become executable", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(
        decideTapLinger,
        createTapLingerState(),
        enter(1000),
        makeOptions({tapAction: malformedShortcut()}),
    );
    const result = run(decideTapLinger, first.state, tick(1500), makeOptions({tapAction: malformedShortcut()}));

    assert.deepEqual(plain(first.effects), []);
    assert.equal(first.reason, "pending");
    assert.deepEqual(plain(first.status), {
        tap: "malformed",
        linger: "valid",
    });
    assert.deepEqual(plain(result.effects), ["linger"]);
    assert.equal(result.reason, "linger");
});

test("malformed linger action does not become executable", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(
        decideTapLinger,
        createTapLingerState(),
        enter(1000),
        makeOptions({lingerAction: malformedShortcut()}),
    );

    assert.deepEqual(plain(result.effects), ["tap"]);
    assert.equal(result.reason, "immediate-tap");
    assert.deepEqual(plain(result.status), {
        tap: "valid",
        linger: "malformed",
    });
});

test("both actions none produce no action", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(
        decideTapLinger,
        createTapLingerState(),
        enter(1000),
        makeOptions({tapAction: none(), lingerAction: none()}),
    );

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.status), {
        tap: "none",
        linger: "none",
    });
});

test("leave at exactly 500 ms follows the inclusive boundary", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());

    const result = run(decideTapLinger, first.state, leave(1500), makeOptions());

    assert.deepEqual(plain(result.effects), ["linger"]);
    assert.equal(result.reason, "linger");
});

test("re-enter after completed tap starts a fresh interaction", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const tapped = run(decideTapLinger, first.state, leave(1200), makeOptions());
    const reentered = run(decideTapLinger, tapped.state, enter(1300), makeOptions());

    assert.deepEqual(plain(reentered.effects), []);
    assert.equal(reentered.reason, "pending");
    assert.deepEqual(plain(reentered.state), {
        active: true,
        enteredAtMs: 1300,
        lastNowMs: 1300,
    });
});

test("re-enter after completed linger starts a fresh interaction", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const lingered = run(decideTapLinger, first.state, tick(1500), makeOptions());
    const reentered = run(decideTapLinger, lingered.state, enter(1600), makeOptions());

    assert.deepEqual(plain(reentered.effects), []);
    assert.equal(reentered.reason, "pending");
    assert.deepEqual(plain(reentered.state), {
        active: true,
        enteredAtMs: 1600,
        lastNowMs: 1600,
    });
});

test("clock regression is ignored deterministically", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const before = plain(first.state);

    const result = run(decideTapLinger, first.state, move(999, 0), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "clock-regression");
    assert.deepEqual(plain(result.state), before);
});

test("duplicate enter while active is ignored", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const result = run(decideTapLinger, first.state, enter(1100), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: true,
        enteredAtMs: 1000,
        lastNowMs: 1100,
    });
});

test("leave while idle is ignored", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(decideTapLinger, createTapLingerState(), leave(1000), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1000,
    });
});

test("tick while idle is ignored", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const result = run(decideTapLinger, createTapLingerState(), tick(1000), makeOptions());

    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1000,
    });
});

test("move back inside after leaving does not revive the old interaction", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const first = run(decideTapLinger, createTapLingerState(), enter(1000), makeOptions());
    const tapped = run(decideTapLinger, first.state, move(1200, 9), makeOptions());
    const result = run(decideTapLinger, tapped.state, move(1300, 0), makeOptions());

    assert.deepEqual(plain(tapped.effects), ["tap"]);
    assert.deepEqual(plain(result.effects), []);
    assert.equal(result.reason, "ignored");
    assert.deepEqual(plain(result.state), {
        active: false,
        enteredAtMs: null,
        lastNowMs: 1300,
    });
});

test("helper returns a new state object and does not mutate inputs", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const state = createTapLingerState();
    const options = makeOptions({tapAction: shortcut("Overview"), lingerAction: shortcut("Show Desktop")});
    const frozenState = structuredClone(state);
    const frozenOptions = structuredClone(options);
    Object.freeze(state);
    Object.freeze(options.tapAction);
    Object.freeze(options.lingerAction);
    Object.freeze(options);

    const result = run(decideTapLinger, state, enter(1000), options);

    assert.deepEqual(plain(state), frozenState);
    assert.deepEqual(plain(options), frozenOptions);
    assert.notStrictEqual(result.state, state);
});

test("repeated calls are deterministic", () => {
    const {createTapLingerState, decideTapLinger} = loadTapLingerHelpers();
    const state = createTapLingerState();
    const options = makeOptions();

    const first = run(decideTapLinger, state, enter(1000), options);
    const second = run(decideTapLinger, createTapLingerState(), enter(1000), options);

    assert.deepEqual(plain(first), plain(second));
});
