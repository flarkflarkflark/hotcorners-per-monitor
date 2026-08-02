const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

function loadCommandClientContext() {
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

function sampleAction() {
    return {
        type: "command",
        program: "/usr/bin/printf",
        arguments: ["%s\\n", "hello world"],
    };
}

test("A: valid command action builds exact Run(program, argumentsJson) call", () => {
    const ctx = loadCommandClientContext();
    const action = sampleAction();

    const call = ctx.buildCommandRequest(action);

    assert.deepEqual(plain(call), {
        bus: "org.flark.HotCorners.CommandRunner",
        objectPath: "/CommandRunner",
        interfaceName: "org.flark.HotCorners.CommandRunner1",
        methodName: "Run",
        program: "/usr/bin/printf",
        argumentsJson: JSON.stringify(["%s\\n", "hello world"]),
    });
});

test("B: argv remains split; no whitespace tokenization", () => {
    const ctx = loadCommandClientContext();
    const action = sampleAction();

    const call = ctx.buildCommandRequest(action);

    assert.equal(JSON.parse(call.argumentsJson).length, 2);
    assert.deepEqual(JSON.parse(call.argumentsJson), ["%s\\n", "hello world"]);
});

test("C: shell-looking tokens remain literal argv data", () => {
    const ctx = loadCommandClientContext();
    const action = {
        type: "command",
        program: "/usr/bin/echo",
        arguments: ["hello; rm -rf /", "$(touch /tmp/x)", "*.txt", "a | b", ">output"],
    };

    const call = ctx.buildCommandRequest(action);

    assert.deepEqual(JSON.parse(call.argumentsJson), action.arguments);
});

test("D: never rewrites into shell wrapper", () => {
    const ctx = loadCommandClientContext();
    const action = {
        type: "command",
        program: "/usr/bin/sh",
        arguments: ["-c", "echo ok"],
    };

    const call = ctx.buildCommandRequest(action);

    assert.equal(call.program, "/usr/bin/sh");
    assert.equal(call.methodName, "Run");
    assert.equal(call.argumentsJson, JSON.stringify(["-c", "echo ok"]));
});

test("E/F: invalid command action is rejected before helper call", () => {
    const ctx = loadCommandClientContext();
    const helperClient = {
        calls: 0,
        call() {
            helperClient.calls++;
            return [true, ""];
        },
    };

    const invalidActions = [
        {type: "command", program: "", arguments: []},
        {type: "command", program: 42, arguments: []},
        {type: "command", program: "/usr/bin/echo", arguments: "no-array"},
        {type: "command", program: "/usr/bin/echo", arguments: ["ok", 1]},
        {type: "command", program: "/usr/bin/echo", arguments: [null]},
    ];

    for (const action of invalidActions) {
        const result = ctx.invokeCommandHelper(action, helperClient);
        assert.equal(result.accepted, false);
    }

    assert.equal(helperClient.calls, 0);
});

test("J: helper success result is normalized", () => {
    const ctx = loadCommandClientContext();
    const action = sampleAction();
    const helperClient = {
        call() {
            return [true, ""];
        },
    };

    const result = ctx.invokeCommandHelper(action, helperClient);

    assert.deepEqual(plain(result), {accepted: true, errorName: ""});
});

test("K: helper rejection result is normalized", () => {
    const ctx = loadCommandClientContext();
    const action = sampleAction();
    const helperClient = {
        call() {
            return [false, "invalid-program"];
        },
    };

    const result = ctx.invokeCommandHelper(action, helperClient);

    assert.deepEqual(plain(result), {accepted: false, errorName: "invalid-program"});
});

test("L: transport errors are caught and normalized", () => {
    const ctx = loadCommandClientContext();
    const action = sampleAction();
    const helperClient = {
        call() {
            throw new Error("dbus unavailable");
        },
    };

    const result = ctx.invokeCommandHelper(action, helperClient);

    assert.deepEqual(plain(result), {accepted: false, errorName: "transport-error"});
});

test("M: unavailable helper client yields explicit unavailable result", () => {
    const ctx = loadCommandClientContext();
    const action = sampleAction();

    const result = ctx.invokeCommandHelper(action, null);

    assert.deepEqual(plain(result), {accepted: false, errorName: "helper-unavailable"});
});

test("N/O/P: non-mutation, one call, and unknown fields ignored", () => {
    const ctx = loadCommandClientContext();
    const action = {
        type: "command",
        program: "/usr/bin/printf",
        arguments: ["%s", "value"],
        xUnknownRoot: {enabled: true},
        workingDirectory: "/tmp/ignored",
        environment: {A: "B"},
        timeoutMs: 1,
    };
    const original = structuredClone(action);
    Object.freeze(action.arguments);
    Object.freeze(action.xUnknownRoot);
    Object.freeze(action);

    const helperClient = {
        calls: [],
        call(...args) {
            helperClient.calls.push(args);
            return {accepted: true, errorName: ""};
        },
    };

    const result = ctx.invokeCommandHelper(action, helperClient);

    assert.deepEqual(plain(result), {accepted: true, errorName: ""});
    assert.deepEqual(action, original);
    assert.equal(helperClient.calls.length, 1);

    const [bus, objectPath, interfaceName, methodName, program, argumentsJson] = helperClient.calls[0];
    assert.equal(bus, "org.flark.HotCorners.CommandRunner");
    assert.equal(objectPath, "/CommandRunner");
    assert.equal(interfaceName, "org.flark.HotCorners.CommandRunner1");
    assert.equal(methodName, "Run");
    assert.equal(program, "/usr/bin/printf");
    assert.deepEqual(JSON.parse(argumentsJson), ["%s", "value"]);
});
