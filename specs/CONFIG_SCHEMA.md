# MonitorConfigs Contract

This document is normative for every `MonitorConfigs` reader and writer. JSON examples use formatted whitespace for clarity; persisted output may be compact.

## Common identifiers

- Output keys are KWin output connector names such as `DP-1`.
- Position keys are exactly `TopLeft`, `Top`, `TopRight`, `Right`, `BottomRight`, `Bottom`, `BottomLeft`, `Left`.
- Activity and virtual-desktop IDs are KDE-provided stable strings.
- All time values are integer milliseconds.

Connector names are not stable monitor hardware identities. v0.2 and v0.3 retain connector-based matching for compatibility. Unknown/disconnected output entries are retained. Automatic hardware reassociation is deferred; v0.4 must evaluate a fingerprint and manual reassignment design before the native KCM model is finalized.

## Actions

Exactly these action shapes are supported:

```json
{"type":"none"}
{"type":"shortcut","component":"kwin","name":"Overview"}
{"type":"command","program":"konsole","arguments":["--new-tab"]}
```

Rules:

- `type` is required.
- A shortcut requires non-empty string `component` and `name` values.
- A command requires a non-empty string `program` and an array of string `arguments`.
- A command never receives implicit shell interpretation.
- `none` is a valid explicit action and, in v3 contexts, blocks fallback.
- Unknown action types and malformed actions are ineligible and never dispatched.

## Legacy v1 input

v1 is the unversioned format shipped by v0.1.0:

```json
{
  "DP-1": {
    "TopLeft": {"type":"shortcut","component":"kwin","name":"Overview"}
  }
}
```

A root object without `schemaVersion` is treated as v1. Any other unversioned root value is invalid.

## Schema v2 (application v0.2)

```json
{
  "schemaVersion": 2,
  "monitors": {
    "DP-1": {
      "TopLeft": {
        "action": {"type":"shortcut","component":"kwin","name":"Overview"},
        "cooldownMs": 350
      }
    }
  }
}
```

Binding rules:

- `action` is required.
- `cooldownMs` is required and ranges from 0 through 10000.
- Newly created bindings default to 350 ms.
- v1 bindings migrate with `cooldownMs: 0` to preserve observable behavior.

## Schema v3 (application v0.3+)

```json
{
  "schemaVersion": 3,
  "contexts": {
    "default": {
      "kind": "default",
      "monitors": {
        "DP-1": {
          "TopLeft": {
            "tap": {"type":"shortcut","component":"kwin","name":"Overview"},
            "linger": {"type":"command","program":"konsole","arguments":[]},
            "lingerMs": 500,
            "cooldownMs": 350
          }
        }
      }
    },
    "activity:f584aaa5-115c-4407-83cb-cc22b68d7ec8": {
      "kind": "activity",
      "activityId": "f584aaa5-115c-4407-83cb-cc22b68d7ec8",
      "monitors": {}
    },
    "desktop:975a916c-4504-4b7f-bf06-7fd7538a050b": {
      "kind": "desktop",
      "desktopId": "975a916c-4504-4b7f-bf06-7fd7538a050b",
      "monitors": {}
    },
    "activity:f584aaa5-115c-4407-83cb-cc22b68d7ec8|desktop:975a916c-4504-4b7f-bf06-7fd7538a050b": {
      "kind": "activityDesktop",
      "activityId": "f584aaa5-115c-4407-83cb-cc22b68d7ec8",
      "desktopId": "975a916c-4504-4b7f-bf06-7fd7538a050b",
      "monitors": {}
    }
  }
}
```

Binding rules:

- `tap` is required and may be `none`.
- `linger` is optional. Missing `linger` means immediate tap dispatch on activation.
- When `linger` exists, `lingerMs` is required and ranges from 100 through 10000; new bindings default to 500.
- `cooldownMs` is required and ranges from 0 through 10000.
- v2 bindings migrate into `contexts.default`, mapping `action` to `tap` and preserving `cooldownMs` exactly.

Context rules:

- `default` is required and has `kind: default`.
- Other context keys and their IDs must agree with their fields.
- Resolution occurs independently for each output and position.
- Precedence is combined activity+desktop, activity, desktop, default.
- Within the ordered context precedence, the first context that contains the output/position binding wins.
- An explicit binding whose `tap` is `none` wins and blocks fallback.
- A missing binding in the requested context may fall through to `contexts.default` at the same output and position.
- Missing/removed activities and desktops remain stored but are not selected at runtime.
- Desktop selection is for the output where the edge activation occurred, not necessarily the active output.

### Context fallback semantics

`contexts` is a map keyed by stable string context IDs. `default` is reserved and is the only fallback context.

For a non-default requested context, resolution is evaluated for the same output name and position in this order:

1. the requested context binding, if present and valid;
2. `contexts.default` at the same output name and position, if present and valid;
3. no action.

For the `default` context itself, resolve only `contexts.default`; do not recurse or chain through other contexts.

Rules:

- Explicit `none` is authoritative and stops lookup immediately.
- Omission is not the same as explicit `none`; only omission may inherit from `contexts.default`.
- Missing output, missing position, or missing binding in the requested context may inherit from `contexts.default` at the same output and position.
- Never inherit from another output, another position, or another non-default context.
- A missing `contexts.default` entry means no fallback.
- Malformed actions are invalid and are excluded from resolution; they are not the same as explicit `none`.
- Unknown extension fields do not affect resolution and are preserved by normalization and persistence.

Examples:

Exact override:

```json
{
  "schemaVersion": 3,
  "contexts": {
    "default": {
      "kind": "default",
      "monitors": {
        "DP-1": {
          "TopLeft": {"tap": {"type":"shortcut","component":"kwin","name":"Overview"}}
        }
      }
    },
    "activity:work": {
      "kind": "activity",
      "activityId": "work",
      "monitors": {
        "DP-1": {
          "TopLeft": {"tap": {"type":"shortcut","component":"kwin","name":"Show Desktop"}}
        }
      }
    }
  }
}
```

Result: the `activity:work` shortcut.

Omission inherits:

```json
{
  "schemaVersion": 3,
  "contexts": {
    "default": {
      "kind": "default",
      "monitors": {
        "DP-1": {
          "TopLeft": {"tap": {"type":"shortcut","component":"kwin","name":"Overview"}}
        }
      }
    },
    "activity:work": {
      "kind": "activity",
      "activityId": "work",
      "monitors": {
        "DP-1": {
          "TopRight": {"tap": {"type":"shortcut","component":"kwin","name":"Show Desktop"}}
        }
      }
    }
  }
}
```

Result: `contexts.default.monitors["DP-1"].TopLeft`.

Explicit none blocks:

```json
{
  "schemaVersion": 3,
  "contexts": {
    "default": {
      "kind": "default",
      "monitors": {
        "DP-1": {
          "TopLeft": {"tap": {"type":"shortcut","component":"kwin","name":"Overview"}}
        }
      }
    },
    "activity:work": {
      "kind": "activity",
      "activityId": "work",
      "monitors": {
        "DP-1": {
          "TopLeft": {"tap": {"type":"none"}}
        }
      }
    }
  }
}
```

Result: none.

Position isolation:

```json
{
  "schemaVersion": 3,
  "contexts": {
    "default": {
      "kind": "default",
      "monitors": {
        "DP-1": {
          "TopRight": {"tap": {"type":"shortcut","component":"kwin","name":"Overview"}}
        }
      }
    },
    "activity:work": {
      "kind": "activity",
      "activityId": "work",
      "monitors": {}
    }
  }
}
```

Result: no action for `DP-1` / `TopLeft`.

Output isolation:

```json
{
  "schemaVersion": 3,
  "contexts": {
    "default": {
      "kind": "default",
      "monitors": {
        "DP-1": {
          "TopLeft": {"tap": {"type":"shortcut","component":"kwin","name":"Overview"}}
        }
      }
    },
    "activity:work": {
      "kind": "activity",
      "activityId": "work",
      "monitors": {
        "HDMI-A-1": {}
      }
    }
  }
}
```

Result: no action for `HDMI-A-1` / `TopLeft`.

## Validation and forward compatibility

Runtime readers:

- Invalid JSON, a non-object root, an unsupported `schemaVersion`, or a missing required root field invalidates the whole document; no actions run.
- Within a supported root document, an invalid context, monitor, position or binding invalidates that item only. Valid siblings remain eligible.
- Unknown fields are ignored by runtime readers.
- Invalid values are logged without logging command arguments.

Writers:

- Keep the exact raw value and a digest from load time.
- Unsupported versions and invalid roots open read-only with Apply disabled; the original value is never replaced automatically.
- Before Apply, reread the raw value. If its digest changed, block Apply and require Reload; do not silently merge stale state.
- Preserve unknown fields within a supported schema when editing known values.
- Normalize and write the current schema only after validation succeeds.
- Never convert malformed input to an empty configuration on Apply.

## Runtime activation identity

One activation key is:

```text
resolved-context-key + output-name + position
```

Cooldown state is isolated by that key. Cooldown starts only after an eligible action is accepted for dispatch. A suppressed, malformed or `none` action does not start a new cooldown.

Output detection must evaluate all current output geometries using half-open logical-coordinate rectangles. Exactly one matching output is required. Zero matches or overlapping/cloned geometries are ambiguous and fail closed. At an ordinary shared boundary, half-open rectangles select exactly one side. Hot-unplug with no matching output produces no action.

## Tap/linger state machine

The implementation must first prove a timer mechanism on Plasma 6.4; `QTimer` is present in KWin 6.7 source but is not part of the published scripting API contract.

For a binding with a linger action:

1. On edge callback, capture output, position, resolved context, binding and current config generation.
2. Start one pending cycle and a timer for `lingerMs`.
3. The active zone is measured in output-local logical pixels with a proposed tolerance of 8 px:
   - corner: within 8 px of both named sides;
   - edge: within 8 px of the named side.
4. Leaving the zone before the threshold dispatches tap and closes the cycle.
5. Timer expiry while still in the zone dispatches linger and closes the cycle. At the exact threshold, timer expiry wins.
6. Re-entry after closure requires a new KWin edge callback.
7. A repeated callback for the same activation key while pending is ignored.
8. A callback for a different key closes the previous pending cycle as an early leave, then starts the new cycle.
9. Activity/desktop changes do not retarget a pending cycle; it uses the captured context.
10. Output removal, ambiguous output detection, script reconfigure or invalidated configuration cancels the pending cycle without dispatch.

At most one eligible tap or linger action can be dispatched per cycle. Cooldown may suppress that action, so zero dispatches is valid.
