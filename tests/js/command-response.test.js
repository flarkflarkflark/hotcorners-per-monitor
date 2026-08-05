const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

// KWin's callDBus is documented as always asynchronous:
//   callDBus(service, path, interface, method, arg..., callback = QJSValue())
//   "The D-Bus call is always performed in an async way invoking the callback
//    provided as the last (optional) argument. The reply values of the D-Bus
//    method call are passed to the callback."
//   -- https://develop.kde.org/docs/plasma/kwin/api/
//
// It therefore never returns the reply. The helper's Run() is declared
// @pyqtSlot(..., result="QVariantList"), which introspects on the live system
// as `<arg type="av" direction="out"/>` -- an array of variants, so the reply
// can reach the callback either as one array argument or as separate
// arguments, and individual values may arrive variant-wrapped.

function loadContext({callDBusImpl} = {}) {
    const dbusCalls = [];
    const prints = [];
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
        callDBus(...args) {
            dbusCalls.push(args);
            if (callDBusImpl) {
                return callDBusImpl(...args);
            }
            return undefined;
        },
        print(...args) { prints.push(args.join(" ")); },
    });
    vm.runInContext(backendSource, context, {filename: BACKEND_PATH});
    context.__dbusCalls = dbusCalls;
    context.__prints = prints;
    return context;
}

function sampleAction() {
    return {
        type: "command",
        program: "/usr/bin/printf",
        arguments: ["%s\\n", "hello"],
    };
}

// Invokes the helper and returns every reported result.
function collect(ctx, action, helperClient) {
    const results = [];
    ctx.invokeCommandHelper(action, helperClient, function(result) {
        results.push({accepted: result.accepted, errorName: result.errorName});
    });
    return results;
}

// A helper client that answers through the callback, like real callDBus.
function replyingClient(reply) {
    return {
        calls: [],
        call(...args) {
            this.calls.push(args);
            const callback = args[args.length - 1];
            if (typeof callback === "function") {
                reply(callback);
            }
        },
    };
}

test("a genuine success reply reports accepted with no error", () => {
    const ctx = loadContext();
    const results = collect(ctx, sampleAction(), replyingClient(cb => cb(true, "")));

    assert.deepEqual(results, [{accepted: true, errorName: ""}]);
});

test("a success reply delivered as one array argument is accepted", () => {
    // The QVariantList ("av") arriving as a single array argument.
    const ctx = loadContext();
    const results = collect(ctx, sampleAction(), replyingClient(cb => cb([true, ""])));

    assert.deepEqual(results, [{accepted: true, errorName: ""}]);
});

test("a variant-wrapped success reply is unwrapped and accepted", () => {
    const ctx = loadContext();
    const results = collect(ctx, sampleAction(), replyingClient(
        cb => cb([{value: true}, {value: ""}]),
    ));

    assert.deepEqual(results, [{accepted: true, errorName: ""}]);
});

test("a rejection reply preserves the helper's error name", () => {
    const ctx = loadContext();
    const results = collect(ctx, sampleAction(), replyingClient(
        cb => cb(false, "program-not-found"),
    ));

    assert.deepEqual(results, [{accepted: false, errorName: "program-not-found"}]);
});

test("a rejection reply delivered as one array argument is preserved", () => {
    const ctx = loadContext();
    const results = collect(ctx, sampleAction(), replyingClient(
        cb => cb([false, "invalid-program"]),
    ));

    assert.deepEqual(results, [{accepted: false, errorName: "invalid-program"}]);
});

test("malformed replies still fail closed as invalid-helper-response", () => {
    const malformedReplies = [
        cb => cb(),
        cb => cb(null),
        cb => cb(true),
        cb => cb([true]),
        cb => cb(["yes", ""]),
        cb => cb([true, 1]),
        cb => cb("not-a-reply"),
        cb => cb([]),
    ];

    for (const reply of malformedReplies) {
        const ctx = loadContext();
        const results = collect(ctx, sampleAction(), replyingClient(reply));

        assert.equal(results.length, 1);
        assert.equal(results[0].accepted, false);
        assert.equal(
            results[0].errorName, "invalid-helper-response",
            `reply ${reply} should fail closed`,
        );
    }
});

test("a D-Bus transport failure reports transport-error exactly once", () => {
    const ctx = loadContext();
    const helperClient = {
        call() { throw new Error("dbus unavailable"); },
    };

    const results = collect(ctx, sampleAction(), helperClient);

    assert.deepEqual(results, [{accepted: false, errorName: "transport-error"}]);
});

test("the reply callback is passed to the helper as the last argument", () => {
    const ctx = loadContext();
    const helperClient = replyingClient(cb => cb(true, ""));

    collect(ctx, sampleAction(), helperClient);

    assert.equal(helperClient.calls.length, 1);
    const args = helperClient.calls[0];
    assert.equal(typeof args[args.length - 1], "function");
    // bus, path, interface, method, program, argumentsJson, callback
    assert.equal(args.length, 7);
    assert.equal(args[0], "org.flark.HotCorners.CommandRunner");
    assert.equal(args[3], "Run");
    assert.equal(args[4], "/usr/bin/printf");
});

test("the real helper client forwards a callback to callDBus", () => {
    const ctx = loadContext();
    const client = ctx.createCommandHelperClient();
    const callback = function() {};

    client.call("bus", "/path", "iface", "Run", "/usr/bin/true", "[]", callback);

    assert.equal(ctx.__dbusCalls.length, 1);
    const args = ctx.__dbusCalls[0];
    assert.equal(args.length, 7);
    assert.equal(args[6], callback);
});

test("a successful dispatch through executeAction logs no helper error", () => {
    // Regression: the live system logged invalid-helper-response on every
    // genuine success because callDBus's async reply was never collected.
    const ctx = loadContext({
        callDBusImpl(...args) {
            const callback = args[args.length - 1];
            if (typeof callback === "function") {
                callback([true, ""]);
            }
        },
    });

    ctx.executeAction(sampleAction());

    assert.deepEqual(
        ctx.__prints.filter(line => line.includes("command helper error")),
        [],
    );
});

test("a rejected dispatch through executeAction logs the helper error name", () => {
    const ctx = loadContext({
        callDBusImpl(...args) {
            const callback = args[args.length - 1];
            if (typeof callback === "function") {
                callback([false, "program-not-found"]);
            }
        },
    });

    ctx.executeAction(sampleAction());

    assert.equal(
        ctx.__prints.some(line =>
            line.includes("command helper error: program-not-found")),
        true,
    );
});

test("a reply that never arrives reports nothing rather than a false error", () => {
    // callDBus returning undefined must not itself be treated as a reply.
    const ctx = loadContext();
    const silentClient = {call() {}};

    const results = collect(ctx, sampleAction(), silentClient);

    assert.deepEqual(results, []);
});

test("invalid actions are still rejected before any helper call", () => {
    const invalidActions = [
        {type: "command", program: "", arguments: []},
        {type: "command", program: "/usr/bin/echo", arguments: "no-array"},
        {type: "command", program: "/usr/bin/echo", arguments: ["ok", 1]},
    ];

    for (const action of invalidActions) {
        const ctx = loadContext();
        const helperClient = replyingClient(cb => cb(true, ""));
        const results = collect(ctx, action, helperClient);

        assert.equal(results.length, 1);
        assert.equal(results[0].accepted, false);
        assert.equal(helperClient.calls.length, 0);
    }
});

test("an unavailable helper client reports helper-unavailable", () => {
    const ctx = loadContext();

    assert.deepEqual(collect(ctx, sampleAction(), null), [
        {accepted: false, errorName: "helper-unavailable"},
    ]);
});
