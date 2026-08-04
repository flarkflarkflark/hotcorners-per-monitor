const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const BACKEND_PATH = path.join(ROOT, "kwin-script/contents/code/main.js");
const backendSource = fs.readFileSync(BACKEND_PATH, "utf8");

function loadResolverFunction() {
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
    return context.resolveContextAction;
}

function nullObject(entries = {}) {
    const object = Object.create(null);
    for (const [key, value] of Object.entries(entries)) {
        object[key] = value;
    }
    return object;
}

function shortcut(name) {
    return {type: "shortcut", component: "kwin", name};
}

function none(extra = {}) {
    return Object.assign({type: "none"}, extra);
}

function malformed(type, extra = {}) {
    return Object.assign({type}, extra);
}

function binding(tap, extra = {}) {
    return Object.assign({tap}, extra);
}

function context(kind, monitors = {}) {
    return {
        kind,
        monitors,
    };
}

function makeConfig(contexts, extra = {}) {
    return Object.assign({
        schemaVersion: 3,
        contexts,
    }, extra);
}

function resolve(resolver, config, contextKey, outputName, position) {
    return resolver(config, contextKey, outputName, position);
}

function deepFreeze(value) {
    if (!value || typeof value !== "object" || Object.isFrozen(value)) {
        return value;
    }
    Object.freeze(value);
    for (const key of Object.keys(value)) {
        deepFreeze(value[key]);
    }
    return value;
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

function baseContexts() {
    return {
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
        "activity:work": context("activity", {
            "DP-1": {
                TopLeft: binding(shortcut("Show Desktop")),
            },
        }),
    };
}

test("resolver function is exposed by the backend script", () => {
    assert.equal(typeof loadResolverFunction(), "function");
});

test("exact context match wins over default", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig(baseContexts());

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Show Desktop"},
    });
});

test("exact explicit none blocks default fallback", () => {
    const resolver = loadResolverFunction();
    const contexts = baseContexts();
    contexts["activity:work"].monitors["DP-1"].TopLeft = binding(none());
    const config = makeConfig(contexts);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "none"},
    });
});

test("missing exact binding falls back to contexts.default", () => {
    const resolver = loadResolverFunction();
    const contexts = baseContexts();
    delete contexts["activity:work"].monitors["DP-1"].TopLeft;
    const config = makeConfig(contexts);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("missing exact and missing default returns null", () => {
    const resolver = loadResolverFunction();
    const contexts = baseContexts();
    delete contexts["activity:work"].monitors["DP-1"].TopLeft;
    delete contexts.default.monitors["DP-1"].TopLeft;
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "activity:work", "DP-1", "TopLeft"), null);
});

test("default explicit none is returned", () => {
    const resolver = loadResolverFunction();
    const contexts = baseContexts();
    contexts.default.monitors["DP-1"].TopLeft = binding(none());
    delete contexts["activity:work"].monitors["DP-1"].TopLeft;
    const config = makeConfig(contexts);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "none"},
    });
});

test("resolving default uses only contexts.default", () => {
    const resolver = loadResolverFunction();
    const contexts = baseContexts();
    delete contexts.default.monitors["DP-1"].TopLeft;
    contexts.default.monitors["DP-1"].TopRight = binding(shortcut("Overview"));
    contexts["activity:work"].monitors["DP-1"].TopLeft = binding(shortcut("Show Desktop"));
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "default", "DP-1", "TopLeft"), null);
});

test("missing contexts.default returns null", () => {
    const resolver = loadResolverFunction();
    const contexts = baseContexts();
    delete contexts.default;
    delete contexts["activity:work"].monitors["DP-1"].TopLeft;
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "activity:work", "DP-1", "TopLeft"), null);
});

test("output isolation prevents cross-output fallback", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
        "activity:work": context("activity", {
            "HDMI-A-1": {
                TopLeft: binding(shortcut("Show Desktop")),
            },
        }),
    };
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "activity:work", "HDMI-A-1", "TopRight"), null);
});

test("position isolation prevents cross-position fallback", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {
            "DP-1": {
                TopRight: binding(shortcut("Overview")),
            },
        }),
        "activity:work": context("activity", {
            "DP-1": {},
        }),
    };
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "activity:work", "DP-1", "TopLeft"), null);
});

test("no inheritance from another non-default context", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {}),
        "activity:work": context("activity", {
            "DP-1": {},
        }),
        "activity:play": context("activity", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
    };
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "activity:work", "DP-1", "TopLeft"), null);
});

test("unknown current context may use contexts.default", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig({
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
    });

    const result = resolve(resolver, config, "activity:unknown", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("missing output in exact context may inherit same output and position from default", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
        "activity:work": context("activity", {
            "HDMI-A-1": {},
        }),
    };
    const config = makeConfig(contexts);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("missing position in exact context may inherit same output and position from default", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
        "activity:work": context("activity", {
            "DP-1": {
                TopRight: binding(shortcut("Show Desktop")),
            },
        }),
    };
    const config = makeConfig(contexts);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("malformed exact action does not become executable", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview")),
            },
        }),
        "activity:work": context("activity", {
            "DP-1": {
                TopLeft: binding(malformed("shortcut", {component: "", name: "Broken"})),
            },
        }),
    };
    const config = makeConfig(contexts);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("malformed default action does not become executable", () => {
    const resolver = loadResolverFunction();
    const contexts = {
        default: context("default", {
            "DP-1": {
                TopLeft: binding(malformed("shortcut", {component: "", name: "Broken"})),
            },
        }),
        "activity:work": context("activity", {
            "DP-1": {},
        }),
    };
    const config = makeConfig(contexts);

    assert.equal(resolve(resolver, config, "activity:work", "DP-1", "TopLeft"), null);
});

test("explicit none remains distinguishable from missing", () => {
    const resolver = loadResolverFunction();
    const noneConfig = makeConfig({
        default: context("default", {
            "DP-1": {
                TopLeft: binding(none()),
            },
        }),
    });
    const missingConfig = makeConfig({
        default: context("default", {
            "DP-1": {},
        }),
    });

    assert.deepEqual(plain(resolve(resolver, noneConfig, "default", "DP-1", "TopLeft")), {
        tap: {type: "none"},
    });
    assert.equal(resolve(resolver, missingConfig, "default", "DP-1", "TopLeft"), null);
});

test("unknown extension fields do not affect resolution", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig({
        default: context("default", {
            "DP-1": {
                TopLeft: binding(shortcut("Overview"), {
                    xTestBindingHint: "preserve-me",
                    tap: Object.assign(shortcut("Overview"), {xTestActionMetadata: {ok: true}}),
                }),
            },
        }, {
            xTestContextHint: "preserve-me",
        }),
    }, {
        xTestRootMetadata: {enabled: true},
    });

    const result = resolve(resolver, config, "activity:unknown", "DP-1", "TopLeft");

    assert.deepEqual(plain(result), {
        tap: {
            type: "shortcut",
            component: "kwin",
            name: "Overview",
            xTestActionMetadata: {ok: true},
        },
        xTestBindingHint: "preserve-me",
    });
});

test("resolver does not mutate its inputs", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig(baseContexts(), {
        xTestRootHint: {mutable: false},
    });
    const original = structuredClone(config);
    deepFreeze(config);

    resolve(resolver, config, "activity:work", "DP-1", "TopLeft");
    resolve(resolver, config, "activity:work", "DP-1", "TopRight");

    assert.deepEqual(config, original);
});

test("repeated calls are deterministic", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig(baseContexts());

    const first = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");
    const second = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(plain(first), plain(second));
});

test("prototype-safe context key __proto__", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "__proto__", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("prototype-safe context key constructor", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "constructor", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("prototype-safe context key toString", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "toString", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("special-character context identifiers are handled literally", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
        "activity:work / demo": context("activity", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Show Desktop")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "activity:work / demo", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Show Desktop"},
    });
});

test("Unicode context identifiers are handled literally", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
        "activity:工程": context("activity", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Show Desktop")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "activity:工程", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Show Desktop"},
    });
});

test("special-character output names are handled literally", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1 / 4K:HDR": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "default", "DP-1 / 4K:HDR", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Overview"},
    });
});

test("no key collisions occur when context IDs resemble one another", () => {
    const resolver = loadResolverFunction();
    const contexts = nullObject({
        default: context("default", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Overview")),
            }),
        })),
        "activity:a:b": context("activity", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Show Desktop")),
            }),
        })),
        "activity:a": context("activity", nullObject({
            "DP-1": nullObject({
                TopLeft: binding(shortcut("Lock Session")),
            }),
        })),
    });
    const config = makeConfig(contexts);

    assert.deepEqual(plain(resolve(resolver, config, "activity:a:b", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Show Desktop"},
    });
    assert.deepEqual(plain(resolve(resolver, config, "activity:a", "DP-1", "TopLeft")), {
        tap: {type: "shortcut", component: "kwin", name: "Lock Session"},
    });
});

test("returned bindings are defensive copies of the stored binding", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig(baseContexts());

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.notStrictEqual(result, config.contexts["activity:work"].monitors["DP-1"].TopLeft);
    assert.notStrictEqual(result.tap, config.contexts["activity:work"].monitors["DP-1"].TopLeft.tap);
    assert.deepEqual(plain(result), plain(config.contexts["activity:work"].monitors["DP-1"].TopLeft));
});

test("root, context, monitor, binding and action objects remain unchanged", () => {
    const resolver = loadResolverFunction();
    const config = makeConfig(baseContexts(), {
        xTestRootField: {ok: true},
    });
    const original = structuredClone(config);
    deepFreeze(config);

    const result = resolve(resolver, config, "activity:work", "DP-1", "TopLeft");

    assert.deepEqual(config, original);
    assert.deepEqual(plain(result), {
        tap: {type: "shortcut", component: "kwin", name: "Show Desktop"},
    });
});
