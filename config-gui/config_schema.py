"""Versioned MonitorConfigs schema helpers.

This module has no persistence or UI responsibilities. It only validates and
normalizes supported configuration documents.
"""

from copy import deepcopy


SCHEMA_VERSION = 2
SCHEMA_VERSION_V3 = 3
DEFAULT_COOLDOWN_MS = 350
LEGACY_COOLDOWN_MS = 0
MAX_COOLDOWN_MS = 10_000
DEFAULT_LINGER_MS = 500
MIN_LINGER_MS = 100
MAX_LINGER_MS = 10_000
MAX_COMMAND_PROGRAM_BYTES = 4096
MAX_COMMAND_ARGUMENTS = 128
MAX_COMMAND_ARGUMENT_BYTES = 16 * 1024
MAX_COMMAND_TOTAL_ARGUMENT_BYTES = 128 * 1024
CONTEXT_KINDS = frozenset({"default", "activity", "desktop", "activityDesktop"})
POSITIONS = frozenset({
    "TopLeft",
    "Top",
    "TopRight",
    "Right",
    "BottomRight",
    "Bottom",
    "BottomLeft",
    "Left",
})


class InvalidConfig(ValueError):
    """Raised when the root document cannot be normalized safely."""


class UnsupportedSchemaVersion(InvalidConfig):
    """Raised when a document uses a schema version this release cannot read."""


def _is_object(value):
    return isinstance(value, dict)


def _utf8_byte_length(value):
    return len(value.encode("utf-8"))


def validate_command_program(program):
    if not isinstance(program, str) or not program:
        return False, "invalid-program"
    if "\x00" in program:
        return False, "invalid-program"
    if _utf8_byte_length(program) > MAX_COMMAND_PROGRAM_BYTES:
        return False, "invalid-program"
    return True, ""


def validate_command_arguments(arguments):
    if not isinstance(arguments, list):
        return False, "invalid-arguments"
    if len(arguments) > MAX_COMMAND_ARGUMENTS:
        return False, "invalid-arguments"

    total_bytes = 0
    for argument in arguments:
        if not isinstance(argument, str):
            return False, "invalid-arguments"
        if "\x00" in argument:
            return False, "invalid-arguments"

        size = _utf8_byte_length(argument)
        if size > MAX_COMMAND_ARGUMENT_BYTES:
            return False, "invalid-arguments"

        total_bytes += size
        if total_bytes > MAX_COMMAND_TOTAL_ARGUMENT_BYTES:
            return False, "invalid-arguments"

    return True, ""


def build_command_action(program, arguments):
    program_ok, program_error = validate_command_program(program)
    if not program_ok:
        raise InvalidConfig(program_error)

    arguments_ok, arguments_error = validate_command_arguments(arguments)
    if not arguments_ok:
        raise InvalidConfig(arguments_error)

    return {
        "type": "command",
        "program": program,
        "arguments": deepcopy(arguments),
    }


def normalize_action(action):
    return _normalize_action(action)


def _valid_context_id(value):
    return isinstance(value, str) and bool(value) and "\x00" not in value


def validate_context_metadata(kind, activity_id=None, desktop_id=None):
    if kind not in CONTEXT_KINDS:
        return False, "invalid-context"
    if kind == "default":
        if activity_id is not None or desktop_id is not None:
            return False, "invalid-context"
        return True, ""
    if kind == "activity":
        if _valid_context_id(activity_id) and desktop_id is None:
            return True, ""
        return False, "invalid-context"
    if kind == "desktop":
        if _valid_context_id(desktop_id) and activity_id is None:
            return True, ""
        return False, "invalid-context"
    if kind == "activityDesktop":
        if _valid_context_id(activity_id) and _valid_context_id(desktop_id):
            return True, ""
        return False, "invalid-context"
    return False, "invalid-context"


def build_context_key(kind, activity_id=None, desktop_id=None):
    ok, error = validate_context_metadata(kind, activity_id, desktop_id)
    if not ok:
        raise InvalidConfig(error)
    if kind == "default":
        return "default"
    if kind == "activity":
        return f"activity:{activity_id}"
    if kind == "desktop":
        return f"desktop:{desktop_id}"
    return f"activity:{activity_id}|desktop:{desktop_id}"


def _normalize_action(action):
    if not _is_object(action):
        return None

    action_type = action.get("type")
    normalized = deepcopy(action)
    if action_type == "none":
        normalized["type"] = "none"
        return normalized
    if action_type == "shortcut":
        component = action.get("component")
        name = action.get("name")
        if (isinstance(component, str) and component
                and isinstance(name, str) and name):
            normalized["type"] = "shortcut"
            normalized["component"] = component
            normalized["name"] = name
            return normalized
        return None
    if action_type == "command":
        try:
            command_action = build_command_action(
                action.get("program"),
                action.get("arguments"),
            )
        except InvalidConfig:
            return None
        normalized["type"] = "command"
        normalized["program"] = command_action["program"]
        normalized["arguments"] = command_action["arguments"]
        return normalized
    return None


def _valid_cooldown(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_COOLDOWN_MS
    )


def validate_cooldown_ms(value):
    if not _valid_cooldown(value):
        return False, "invalid-cooldown"
    return True, ""


def normalize_cooldown_ms(value, default=DEFAULT_COOLDOWN_MS):
    ok, _error = validate_cooldown_ms(value)
    if ok:
        return int(value)

    default_ok, _default_error = validate_cooldown_ms(default)
    if default_ok:
        return int(default)

    raise InvalidConfig("invalid cooldownMs")


def _valid_linger_ms(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and MIN_LINGER_MS <= value <= MAX_LINGER_MS
    )


def validate_linger_ms(value):
    if not _valid_linger_ms(value):
        return False, "invalid-linger-ms"
    return True, ""


def normalize_linger_ms(value, default=DEFAULT_LINGER_MS):
    ok, _error = validate_linger_ms(value)
    if ok:
        return int(value)

    default_ok, _default_error = validate_linger_ms(default)
    if default_ok:
        return int(default)

    raise InvalidConfig("invalid lingerMs")


def create_v2_binding(action, cooldown_ms=DEFAULT_COOLDOWN_MS):
    """Create one validated v2 binding using the new-binding default."""
    normalized_action = _normalize_action(action)
    if normalized_action is None:
        raise InvalidConfig("invalid action")
    if not _valid_cooldown(cooldown_ms):
        raise InvalidConfig("invalid cooldownMs")
    return {
        "action": normalized_action,
        "cooldownMs": int(cooldown_ms),
    }


def _normalize_monitors(monitors, *, legacy):
    if not _is_object(monitors):
        raise InvalidConfig("monitors must be an object")

    normalized = {}
    for output_name, monitor in monitors.items():
        if not isinstance(output_name, str) or not output_name or not _is_object(monitor):
            continue

        normalized_monitor = {} if legacy else deepcopy(monitor)
        for position, value in monitor.items():
            if position not in POSITIONS:
                continue

            if not legacy:
                normalized_monitor.pop(position, None)

            if legacy:
                action = _normalize_action(value)
                if action is None:
                    continue
                normalized_monitor[position] = {
                    "action": action,
                    "cooldownMs": LEGACY_COOLDOWN_MS,
                }
                continue

            if not _is_object(value):
                continue
            action = _normalize_action(value.get("action"))
            cooldown_ms = value.get("cooldownMs")
            if action is None or not _valid_cooldown(cooldown_ms):
                continue
            binding = deepcopy(value)
            binding["action"] = action
            binding["cooldownMs"] = int(cooldown_ms)
            normalized_monitor[position] = binding

        normalized[output_name] = normalized_monitor
    return normalized


def normalize_config_to_v2(config):
    """Normalize an unversioned v0.1 or schema-v2 document to schema v2."""
    if not _is_object(config):
        raise InvalidConfig("configuration root must be an object")

    if "schemaVersion" not in config:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "monitors": _normalize_monitors(config, legacy=True),
        }

    if config.get("schemaVersion") != SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"unsupported schema version: {config.get('schemaVersion')!r}"
        )

    normalized = deepcopy(config)
    normalized["schemaVersion"] = SCHEMA_VERSION
    normalized["monitors"] = _normalize_monitors(
        config.get("monitors"), legacy=False
    )
    return normalized


def migrate_config_v2_to_v3(config):
    """Convert a schema v2 document into the equivalent schema v3 document.

    Per CONFIG_SCHEMA.md, v2 bindings migrate into ``contexts.default``,
    mapping ``action`` to ``tap`` and preserving ``cooldownMs`` exactly. No
    ``linger`` is added: a missing ``linger`` means immediate tap dispatch, so
    the observable behavior is unchanged. Unknown fields are preserved at the
    root, monitor and binding levels.
    """
    if _is_object(config) and config.get("schemaVersion") == SCHEMA_VERSION_V3:
        raise InvalidConfig("document is already schema version 3")

    normalized = normalize_config_to_v2(config)
    monitors = normalized.pop("monitors", {})

    migrated_monitors = {}
    for output_name, monitor in monitors.items():
        migrated_monitor = {}
        for key, value in monitor.items():
            if key not in POSITIONS:
                migrated_monitor[key] = deepcopy(value)
                continue

            binding = deepcopy(value)
            action = binding.pop("action", None)
            if action is None:
                continue
            # Rebuild so `tap` replaces `action` in place rather than being
            # appended after the unknown fields.
            migrated_binding = {"tap": action}
            migrated_binding.update(binding)
            migrated_monitor[key] = migrated_binding
        migrated_monitors[output_name] = migrated_monitor

    migrated = deepcopy(normalized)
    migrated["schemaVersion"] = SCHEMA_VERSION_V3
    existing_contexts = migrated.get("contexts")
    contexts = deepcopy(existing_contexts) if _is_object(existing_contexts) else {}
    contexts["default"] = {"kind": "default", "monitors": migrated_monitors}
    migrated["contexts"] = contexts
    return normalize_config_to_v3(migrated)


def normalize_config_to_v3(config):
    if not _is_object(config):
        raise InvalidConfig("configuration root must be an object")

    if "schemaVersion" not in config:
        raise UnsupportedSchemaVersion("missing schemaVersion for v3 document")

    if config.get("schemaVersion") != SCHEMA_VERSION_V3:
        raise UnsupportedSchemaVersion(
            f"unsupported schema version: {config.get('schemaVersion')!r}"
        )

    contexts = config.get("contexts")
    if not _is_object(contexts):
        raise InvalidConfig("contexts must be an object")

    default_context = contexts.get("default")
    if not _is_object(default_context) or default_context.get("kind") != "default":
        raise InvalidConfig("default context must exist")

    normalized = deepcopy(config)
    normalized["schemaVersion"] = SCHEMA_VERSION_V3
    normalized["contexts"] = deepcopy(contexts)
    return normalized
