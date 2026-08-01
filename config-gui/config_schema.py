"""Versioned MonitorConfigs schema helpers.

This module has no persistence or UI responsibilities. It only validates and
normalizes supported configuration documents.
"""

from copy import deepcopy


SCHEMA_VERSION = 2
DEFAULT_COOLDOWN_MS = 350
LEGACY_COOLDOWN_MS = 0
MAX_COOLDOWN_MS = 10_000
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


def _normalize_action(action):
    if not _is_object(action):
        return None

    action_type = action.get("type")
    if action_type == "none":
        return deepcopy(action)
    if action_type == "shortcut":
        component = action.get("component")
        name = action.get("name")
        if (isinstance(component, str) and component
                and isinstance(name, str) and name):
            return deepcopy(action)
        return None
    if action_type == "command":
        program = action.get("program")
        arguments = action.get("arguments")
        if (isinstance(program, str) and program
                and isinstance(arguments, list)
                and all(isinstance(arg, str) for arg in arguments)):
            return deepcopy(action)
    return None


def _valid_cooldown(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_COOLDOWN_MS
    )


def create_v2_binding(action, cooldown_ms=DEFAULT_COOLDOWN_MS):
    """Create one validated v2 binding using the new-binding default."""
    normalized_action = _normalize_action(action)
    if normalized_action is None:
        raise InvalidConfig("invalid action")
    if not _valid_cooldown(cooldown_ms):
        raise InvalidConfig("invalid cooldownMs")
    return {
        "action": normalized_action,
        "cooldownMs": cooldown_ms,
    }


def _normalize_monitors(monitors, *, legacy):
    if not _is_object(monitors):
        raise InvalidConfig("monitors must be an object")

    normalized = {}
    for output_name, monitor in monitors.items():
        if not isinstance(output_name, str) or not output_name or not _is_object(monitor):
            continue

        normalized_monitor = {}
        for position, value in monitor.items():
            if position not in POSITIONS:
                continue

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
            binding["cooldownMs"] = cooldown_ms
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
    normalized["monitors"] = _normalize_monitors(
        config.get("monitors"), legacy=False
    )
    return normalized
