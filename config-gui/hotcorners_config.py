#!/usr/bin/env python3
# Hot Corners Per Monitor — Configuration GUI
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Configuration GUI for the hotcorners-per-monitor KWin script.

Reads/writes the script's config via kreadconfig6/kwriteconfig6, then triggers
a KWin reconfigure so changes take effect immediately.
"""

import gettext
import copy
import json
import locale
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from context_provider import ContextOption, DBusContextProvider
from config_schema import (
    DEFAULT_COOLDOWN_MS,
    DEFAULT_LINGER_MS,
    MAX_COOLDOWN_MS,
    MAX_LINGER_MS,
    MIN_LINGER_MS,
    InvalidConfig,
    build_context_key,
    build_command_action,
    create_v2_binding,
    normalize_config_to_v2,
    migrate_config_v2_to_v3,
    normalize_config_to_v3,
    normalize_action,
    normalize_cooldown_ms,
    normalize_linger_ms,
    validate_command_arguments,
    validate_command_program,
    validate_cooldown_ms,
    validate_context_metadata,
    validate_linger_ms,
)
from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal
from PyQt6.QtGui import (
    QGuiApplication, QPainter, QPen, QBrush, QColor, QPalette, QFont,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget, QInputDialog,
)

# -----------------------------------------------------------------------------
# i18n setup
# -----------------------------------------------------------------------------
APP_DOMAIN = "hotcorners-config"

def setup_i18n(locale_dirs=None):
    """Initialize gettext using the system locale."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    if locale_dirs is None:
        locale_dirs = [
            Path(__file__).parent / "translations",
            Path("/usr/share/locale"),
            Path.home() / ".local/share/locale",
        ]
    for d in locale_dirs:
        if not d.exists():
            continue
        if not any(d.glob(f"*/LC_MESSAGES/{APP_DOMAIN}.mo")):
            continue
        try:
            gettext.bindtextdomain(APP_DOMAIN, str(d))
            gettext.textdomain(APP_DOMAIN)
            break
        except (OSError, AttributeError):
            continue
    return gettext.gettext

_ = setup_i18n()

# -----------------------------------------------------------------------------
# Config persistence via kreadconfig6 / kwriteconfig6
# -----------------------------------------------------------------------------
KWINRC_GROUP = "Script-hotcorners-per-monitor"
CONFIG_KEY = "MonitorConfigs"
MISSING_CONFIG_SENTINEL_PREFIX = "__HOTCORNERS_PER_MONITOR_MISSING_"


@dataclass(frozen=True)
class ConfigBaseline:
    key_exists: bool
    raw_value: str | None


@dataclass(frozen=True)
class LoadedConfig:
    document: dict | None
    baseline: ConfigBaseline


class ConfigSaveError(RuntimeError):
    """Base class for the distinct ways saving the configuration can fail."""


class StaleConfigError(ConfigSaveError):
    """Raised when MonitorConfigs changed after it was loaded."""


class MissingToolError(ConfigSaveError):
    """Raised when a required KDE command-line tool is not installed."""

    def __init__(self, tool: str):
        super().__init__(f"required tool not found: {tool}")
        self.tool = tool


class ConfigWriteError(ConfigSaveError):
    """Raised when kwriteconfig6 ran but failed to store the configuration."""

    def __init__(self, detail: str = ""):
        super().__init__(detail or "failed to write the configuration")
        self.detail = detail


class InvalidConfigDocumentError(ConfigSaveError):
    """Raised when the in-memory document cannot be normalized for saving."""

    def __init__(self, detail: str = ""):
        super().__init__(detail or "configuration document is not valid")
        self.detail = detail


def describe_save_error(error: ConfigSaveError) -> str:
    """A specific, actionable message for each distinct save failure."""
    if isinstance(error, StaleConfigError):
        return _(
            "The configuration was changed by another program since this "
            "window opened it. Your edits were not saved, and nothing was "
            "overwritten. Choose \"Reload from disk\" to load the current "
            "configuration, then redo your changes."
        )

    if isinstance(error, MissingToolError):
        return _(
            "The required KDE tool \"{tool}\" was not found. It is normally "
            "part of Plasma 6. Nothing was changed. Install it, then try "
            "again."
        ).format(tool=error.tool)

    if isinstance(error, ConfigWriteError):
        detail = error.detail or _("no further detail was reported")
        return _(
            "Writing the configuration to kwinrc failed, so nothing was "
            "changed. Details: {detail}"
        ).format(detail=detail)

    if isinstance(error, InvalidConfigDocumentError):
        detail = error.detail or _("no further detail was reported")
        return _(
            "The configuration could not be prepared for saving, so nothing "
            "was changed. Details: {detail}"
        ).format(detail=detail)

    return _("Saving the configuration failed. Nothing was changed.")


def _read_config_baseline() -> ConfigBaseline:
    missing_sentinel = f"{MISSING_CONFIG_SENTINEL_PREFIX}{uuid4()}__"
    result = subprocess.run(
        ["kreadconfig6", "--file", "kwinrc",
         "--group", KWINRC_GROUP, "--key", CONFIG_KEY,
         "--default", missing_sentinel],
        capture_output=True, text=True, check=False,
    )
    raw = result.stdout.removesuffix("\n")
    if raw == missing_sentinel:
        return ConfigBaseline(False, None)
    return ConfigBaseline(True, raw)


def load_config() -> LoadedConfig:
    """Read config plus its raw baseline without modifying kwinrc."""
    try:
        baseline = _read_config_baseline()
    except FileNotFoundError:
        return LoadedConfig(None, ConfigBaseline(False, None))

    try:
        raw = baseline.raw_value if baseline.key_exists else ""
        parsed = json.loads(raw) if raw else {}
        schema_version = parsed.get("schemaVersion") if isinstance(parsed, dict) else None
        if schema_version == 3:
            document = normalize_config_to_v3(parsed)
        else:
            document = normalize_config_to_v2(parsed)
    except (json.JSONDecodeError, ValueError):
        document = None
    return LoadedConfig(document, baseline)


def save_config(
        config: dict | None,
        baseline: ConfigBaseline,
) -> ConfigBaseline:
    """Write the config only if its raw baseline is still current.

    Raises a specific ConfigSaveError subclass on failure so the caller can
    tell a concurrent edit apart from a missing tool or a failed write.
    """
    try:
        if isinstance(config, dict) and config.get("schemaVersion") == 3:
            normalized = normalize_config_to_v3(config)
        else:
            normalized = normalize_config_to_v2(config)
        payload = json.dumps(normalized, separators=(",", ":"))
    except (ValueError, TypeError) as exc:
        raise InvalidConfigDocumentError(str(exc)) from exc

    try:
        current = _read_config_baseline()
    except FileNotFoundError as exc:
        raise MissingToolError("kreadconfig6") from exc

    if current != baseline:
        raise StaleConfigError("MonitorConfigs changed since load")

    try:
        subprocess.run(
            ["kwriteconfig6", "--file", "kwinrc",
             "--group", KWINRC_GROUP, "--key", CONFIG_KEY, payload],
            check=True,
        )
    except FileNotFoundError as exc:
        raise MissingToolError("kwriteconfig6") from exc
    except subprocess.CalledProcessError as exc:
        raise ConfigWriteError(
            f"kwriteconfig6 exited with status {exc.returncode}") from exc

    updated_baseline = ConfigBaseline(True, payload)
    try:
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
            check=False,
        )
    except FileNotFoundError:
        pass
    return updated_baseline

# -----------------------------------------------------------------------------
# Action catalog
# -----------------------------------------------------------------------------
BUILTIN_SHORTCUTS_RAW = [
    ("kwin", "Overview", "Overview (show all windows)"),
    ("kwin", "Grid View", "Grid View (virtual desktops)"),
    ("kwin", "Show Desktop", "Show Desktop"),
    ("kwin", "Cycle Overview", "Cycle Overview / Grid"),
    ("kwin", "Window Maximize", "Maximize active window"),
    ("kwin", "Window Minimize", "Minimize active window"),
    ("kwin", "Window Close", "Close active window"),
    ("kwin", "Edit Tiles", "Edit tile layout"),
    ("plasmashell", "activate application launcher", "Application launcher"),
    ("plasmashell", "show-on-mouse-pos", "Show plasma menu at cursor"),
    ("ksmserver", "Lock Session", "Lock screen"),
    ("ksmserver", "Logout", "Log out…"),
]

# Mark strings for xgettext extraction
_("Overview (show all windows)")
_("Grid View (virtual desktops)")
_("Show Desktop")
_("Cycle Overview / Grid")
_("Maximize active window")
_("Minimize active window")
_("Close active window")
_("Edit tile layout")
_("Application launcher")
_("Show plasma menu at cursor")
_("Lock screen")
_("Log out…")

def builtin_shortcuts():
    return [(comp, name, _(label)) for (comp, name, label) in BUILTIN_SHORTCUTS_RAW]

POSITION_LAYOUT = [
    ("TopLeft",     "Top-left"),
    ("Top",         "Top"),
    ("TopRight",    "Top-right"),
    ("Left",        "Left"),
    ("Right",       "Right"),
    ("BottomLeft",  "Bottom-left"),
    ("Bottom",      "Bottom"),
    ("BottomRight", "Bottom-right"),
]
POSITION_IDS = [pid for (pid, _label) in POSITION_LAYOUT]

# Mark for xgettext
_("Top-left"); _("Top"); _("Top-right"); _("Left"); _("Right")
_("Bottom-left"); _("Bottom"); _("Bottom-right")
_("Command"); _("Program"); _("Arguments")
_("Add"); _("Edit"); _("Remove"); _("Move Up"); _("Move Down")
_("Argument")
_("Enter argument value:")
_("Command action runs the program with argv items exactly as listed.")
_("Command program cannot be empty.")
_("Command program is invalid.")
_("Command arguments are invalid.")
_("Cooldown")
_("Minimum time before this hot zone can trigger again.")
_("Invalid cooldown value.")
_("Tap")
_("Linger")
_("Linger delay")
_("Time the cursor must stay before the linger action runs instead of the tap action.")
_("Invalid linger delay value.")
_("Context")
_("Default")
_("Activity")
_("Desktop")
_("Activity + Desktop")
_("Add Context")
_("Edit Context")
_("Remove Context")
_("Inherit from Default")
_("Activity ID")
_("Desktop ID")
_("A context with this identifier already exists.")
_("The default context cannot be removed.")
_("Remove this context?")
_("Invalid context identifier.")

def position_label(pos_id: str) -> str:
    for pid, label in POSITION_LAYOUT:
        if pid == pos_id:
            return _(label)
    return pos_id


def context_kind_label(kind: str) -> str:
    labels = {
        "default": _("Default"),
        "activity": _("Activity"),
        "desktop": _("Desktop"),
        "activityDesktop": _("Activity + Desktop"),
    }
    return labels.get(kind, kind)


def context_display_label(context_key: str, context: dict | None) -> str:
    if not isinstance(context, dict):
        return context_key
    kind = context.get("kind")
    if kind == "default":
        return _("Default")
    if kind == "activity":
        activity_id = context.get("activityId", "")
        return _("Activity: {activity_id}").format(activity_id=activity_id)
    if kind == "desktop":
        desktop_id = context.get("desktopId", "")
        return _("Desktop: {desktop_id}").format(desktop_id=desktop_id)
    if kind == "activityDesktop":
        activity_id = context.get("activityId", "")
        desktop_id = context.get("desktopId", "")
        return _(
            "Activity + Desktop: {activity_id} / {desktop_id}"
        ).format(activity_id=activity_id, desktop_id=desktop_id)
    return context_key

NONE_ACTION = {"type": "none"}
DEFAULT_SHORTCUT_ACTION = {
    "type": "shortcut",
    "component": "kwin",
    "name": "Overview",
}
DEFAULT_COMMAND_ACTION = {
    "type": "command",
    "program": "",
    "arguments": [],
}
KNOWN_ACTION_KEYS = {
    "type",
    "component",
    "name",
    "program",
    "arguments",
}


def _clone_action(action: dict | None) -> dict:
    if not isinstance(action, dict):
        return dict(NONE_ACTION)
    return json.loads(json.dumps(action))


def _merge_action_extensions(base_action: dict | None, canonical_action: dict) -> dict:
    merged = {}
    if isinstance(base_action, dict):
        for key, value in base_action.items():
            if key in KNOWN_ACTION_KEYS:
                continue
            merged[key] = json.loads(json.dumps(value))

    merged.update(json.loads(json.dumps(canonical_action)))
    return merged


def _command_action_from_editor(program: str, arguments: list[str], preserved: dict | None) -> dict:
    ok, error = validate_command_program(program)
    if not ok:
        return _merge_action_extensions(
            preserved,
            {"type": "command", "program": program, "arguments": list(arguments)},
        )

    ok, error = validate_command_arguments(arguments)
    if not ok:
        return _merge_action_extensions(
            preserved,
            {"type": "command", "program": program, "arguments": list(arguments)},
        )

    canonical = build_command_action(program, arguments)
    return _merge_action_extensions(preserved, canonical)


V3_BINDING_INHERIT = "inherit"
V3_BINDING_NONE = "none"
V3_BINDING_LOCAL = "local"


def is_v3_document(config: dict | None) -> bool:
    return (
        isinstance(config, dict)
        and config.get("schemaVersion") == 3
        and isinstance(config.get("contexts"), dict)
    )


def ordered_context_keys(contexts: dict) -> list[str]:
    keys = list(contexts.keys())
    if "default" in contexts:
        keys = ["default"] + [key for key in keys if key != "default"]
    return keys


def get_context_entry(config: dict, context_key: str) -> dict | None:
    contexts = config.get("contexts", {})
    if not isinstance(contexts, dict):
        return None
    entry = contexts.get(context_key)
    return entry if isinstance(entry, dict) else None


def get_context_monitors(config: dict, context_key: str, *, create: bool = False) -> dict | None:
    contexts = config.setdefault("contexts", {})
    entry = contexts.get(context_key)
    if not isinstance(entry, dict):
        if not create:
            return None
        entry = {"kind": "default" if context_key == "default" else "activity", "monitors": {}}
        contexts[context_key] = entry
    monitors = entry.get("monitors")
    if isinstance(monitors, dict):
        return monitors
    if not create:
        return None
    entry["monitors"] = {}
    return entry["monitors"]


def get_context_binding(config: dict, context_key: str, monitor_name: str, position_id: str) -> dict | None:
    contexts = config.get("contexts", {})
    if not isinstance(contexts, dict):
        return None
    context = contexts.get(context_key)
    if not isinstance(context, dict):
        return None
    monitors = context.get("monitors", {})
    if not isinstance(monitors, dict):
        return None
    monitor = monitors.get(monitor_name, {})
    if not isinstance(monitor, dict):
        return None
    binding = monitor.get(position_id)
    return binding if isinstance(binding, dict) else None


def get_default_v3_binding(config: dict, monitor_name: str, position_id: str) -> dict | None:
    return get_context_binding(config, "default", monitor_name, position_id)


def create_v3_binding(
        tap: dict,
        cooldown_ms: int = DEFAULT_COOLDOWN_MS,
        preserved: dict | None = None,
        linger: dict | None = None,
        linger_ms: int = DEFAULT_LINGER_MS,
) -> dict:
    normalized_tap = normalize_action(tap)
    if normalized_tap is None:
        raise InvalidConfig("invalid action")
    if not validate_cooldown_ms(cooldown_ms)[0]:
        raise InvalidConfig("invalid cooldownMs")

    normalized_linger = normalize_action(linger if linger is not None else NONE_ACTION)
    if normalized_linger is None:
        raise InvalidConfig("invalid linger action")
    if not validate_linger_ms(linger_ms)[0]:
        raise InvalidConfig("invalid lingerMs")

    binding = copy.deepcopy(preserved) if isinstance(preserved, dict) else {}
    binding["tap"] = normalized_tap
    binding["linger"] = normalized_linger
    binding["lingerMs"] = int(linger_ms)
    binding["cooldownMs"] = int(cooldown_ms)
    return binding


def remove_v3_binding(config: dict, context_key: str, monitor_name: str, position_id: str) -> None:
    contexts = config.get("contexts", {})
    if not isinstance(contexts, dict):
        return
    context = contexts.get(context_key)
    if not isinstance(context, dict):
        return
    monitors = context.get("monitors")
    if not isinstance(monitors, dict):
        return
    monitor = monitors.get(monitor_name)
    if not isinstance(monitor, dict):
        return
    monitor.pop(position_id, None)
    if not monitor:
        monitors.pop(monitor_name, None)


def set_v3_binding(config: dict, context_key: str, monitor_name: str, position_id: str, binding: dict) -> None:
    monitors = get_context_monitors(config, context_key, create=True)
    if monitors is None:
        return
    monitor = monitors.setdefault(monitor_name, {})
    if not isinstance(monitor, dict):
        monitor = {}
        monitors[monitor_name] = monitor
    monitor[position_id] = copy.deepcopy(binding)


def determine_v3_binding_state(config: dict, context_key: str, monitor_name: str, position_id: str) -> str:
    binding = get_context_binding(config, context_key, monitor_name, position_id)
    if not isinstance(binding, dict):
        return V3_BINDING_INHERIT if context_key != "default" else V3_BINDING_NONE
    tap = binding.get("tap")
    if not isinstance(tap, dict):
        return V3_BINDING_INHERIT if context_key != "default" else V3_BINDING_NONE
    action_type = tap.get("type")
    if action_type == "none":
        return V3_BINDING_NONE
    if action_type in {"shortcut", "command"}:
        return action_type
    return V3_BINDING_INHERIT if context_key != "default" else V3_BINDING_NONE


def effective_v3_binding(config: dict, context_key: str, monitor_name: str, position_id: str) -> dict | None:
    binding = get_context_binding(config, context_key, monitor_name, position_id)
    if isinstance(binding, dict):
        tap = binding.get("tap")
        if isinstance(tap, dict) and tap.get("type") in {"none", "shortcut", "command"}:
            return binding
    if context_key != "default":
        fallback = get_default_v3_binding(config, monitor_name, position_id)
        if isinstance(fallback, dict):
            tap = fallback.get("tap")
            if isinstance(tap, dict) and tap.get("type") in {"none", "shortcut", "command"}:
                return fallback
    return None


def build_context_entry(kind: str, activity_id: str | None = None, desktop_id: str | None = None, preserved: dict | None = None) -> tuple[str, dict]:
    key = build_context_key(kind, activity_id, desktop_id)
    entry = copy.deepcopy(preserved) if isinstance(preserved, dict) else {}
    entry["kind"] = kind
    if kind == "default":
        entry.pop("activityId", None)
        entry.pop("desktopId", None)
    elif kind == "activity":
        entry["activityId"] = activity_id
        entry.pop("desktopId", None)
    elif kind == "desktop":
        entry["desktopId"] = desktop_id
        entry.pop("activityId", None)
    elif kind == "activityDesktop":
        entry["activityId"] = activity_id
        entry["desktopId"] = desktop_id

    monitors = entry.get("monitors")
    if not isinstance(monitors, dict):
        entry["monitors"] = {}
    return key, entry


def set_context_entry(config: dict, old_key: str | None, new_key: str, entry: dict) -> None:
    contexts = config.setdefault("contexts", {})
    if old_key == new_key:
        contexts[new_key] = copy.deepcopy(entry)
        return

    ordered = []
    inserted = False
    for key, value in contexts.items():
        if key == old_key:
            ordered.append((new_key, copy.deepcopy(entry)))
            inserted = True
        elif key != new_key:
            ordered.append((key, value))
    if not inserted:
        if new_key not in contexts:
            ordered.append((new_key, copy.deepcopy(entry)))
        else:
            raise InvalidConfig("context key collision")

    contexts.clear()
    contexts.update(ordered)


def remove_context_entry(config: dict, context_key: str) -> None:
    contexts = config.get("contexts", {})
    if not isinstance(contexts, dict):
        return
    contexts.pop(context_key, None)

# -----------------------------------------------------------------------------
# Monitor detection
# -----------------------------------------------------------------------------
def detect_monitors():
    """Return a list of dicts describing connected outputs."""
    monitors = []
    for screen in QGuiApplication.screens():
        geo = screen.geometry()
        monitors.append({
            "name": screen.name(),
            "manufacturer": screen.manufacturer() or "",
            "model": screen.model() or "",
            "geometry": (geo.x(), geo.y(), geo.width(), geo.height()),
        })
    monitors.sort(key=lambda m: m["geometry"][0])
    return monitors

def display_name(monitor: dict) -> str:
    parts = []
    if monitor["model"]:
        parts.append(monitor["model"])
    elif monitor["manufacturer"]:
        parts.append(monitor["manufacturer"])
    parts.append(f"({monitor['name']})")
    return " ".join(parts)


# -----------------------------------------------------------------------------
# Context dialog — add/edit v3 context metadata
# -----------------------------------------------------------------------------
class ContextDialog(QDialog):
    def __init__(self, parent=None, *, kind="activity", activity_id="",
                 desktop_id="", provider=None):
        super().__init__(parent)
        self.setWindowTitle(_("Context"))
        self._provider = provider if provider is not None else DBusContextProvider()
        self._build_ui()
        self.set_context(kind, activity_id, desktop_id)

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.kind_combo = QComboBox()
        self.kind_combo.addItem(_("Activity"), "activity")
        self.kind_combo.addItem(_("Desktop"), "desktop")
        self.kind_combo.addItem(_("Activity + Desktop"), "activityDesktop")
        self.kind_combo.setToolTip(_(
            "Choose what this context depends on. The binding you edit here "
            "applies only while that activity and/or virtual desktop is current."
        ))
        self.kind_combo.currentIndexChanged.connect(self._update_visibility)
        layout.addRow(_("Context"), self.kind_combo)

        self.activity_combo = QComboBox()
        self.activity_combo.setToolTip(_(
            "The activity this context applies to. The name is shown; the "
            "stable identifier KWin matches on is stored."
        ))
        layout.addRow(_("Activity"), self.activity_combo)
        self.activity_label = layout.labelForField(self.activity_combo)

        self.desktop_combo = QComboBox()
        self.desktop_combo.setToolTip(_(
            "The virtual desktop this context applies to. The name is shown; "
            "the stable identifier KWin matches on is stored."
        ))
        layout.addRow(_("Desktop"), self.desktop_combo)
        self.desktop_label = layout.labelForField(self.desktop_combo)

        self.refresh_button = QPushButton(_("Refresh list"))
        self.refresh_button.setToolTip(_(
            "Look up the current activities and virtual desktops again, for "
            "example after creating or renaming one."
        ))
        self.refresh_button.clicked.connect(self.refresh_options)
        layout.addRow("", self.refresh_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _populate(self, combo, options, selected_id):
        """Fill a combo with discovered options, keeping a stale saved id."""
        combo.clear()
        known = set()
        for option in options:
            label = option.name or option.identifier
            combo.addItem(f"{label} ({option.identifier})", option.identifier)
            known.add(option.identifier)

        if selected_id and selected_id not in known:
            # A saved identifier that no longer resolves stays selectable and
            # is never silently dropped, so the stored context survives.
            combo.addItem(
                _("{identifier} — unavailable").format(identifier=selected_id),
                selected_id,
            )

        if selected_id:
            index = combo.findData(selected_id)
            if index >= 0:
                combo.setCurrentIndex(index)

    def refresh_options(self):
        """Re-query the provider, preserving the current selections."""
        self._populate(
            self.activity_combo, self._provider.activities(), self.activity_id())
        self._populate(
            self.desktop_combo, self._provider.desktops(), self.desktop_id())

    def _update_visibility(self):
        kind = self.kind_combo.currentData() or "activity"
        show_activity = kind in {"activity", "activityDesktop"}
        show_desktop = kind in {"desktop", "activityDesktop"}
        self.activity_combo.setVisible(show_activity)
        self.activity_label.setVisible(show_activity)
        self.desktop_combo.setVisible(show_desktop)
        self.desktop_label.setVisible(show_desktop)

    def set_context(self, kind: str, activity_id: str = "", desktop_id: str = ""):
        idx = self.kind_combo.findData(kind)
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        self._populate(self.activity_combo, self._provider.activities(), activity_id or "")
        self._populate(self.desktop_combo, self._provider.desktops(), desktop_id or "")
        self._update_visibility()

    def context_kind(self):
        return self.kind_combo.currentData() or "activity"

    def activity_id(self):
        return self.activity_combo.currentData() or ""

    def desktop_id(self):
        return self.desktop_combo.currentData() or ""

# -----------------------------------------------------------------------------
# Visual canvas: monitor arrangement with clickable handles
# -----------------------------------------------------------------------------
class MonitorCanvas(QWidget):
    """Top-down visual representation of all monitors with clickable
    corner/edge handles. Click a handle to select that position for editing."""

    cornerSelected = pyqtSignal(str, str)  # (monitor_name, position_id)

    HANDLE_SIZE = 22  # px in widget space
    PADDING = 32
    MIN_MONITOR_LABEL_PT = 8

    def __init__(self, monitors, config, parent=None):
        super().__init__(parent)
        self.monitors = monitors
        self.config = config
        self.selected = None   # (monitor_name, position_id)
        self.hovered = None
        self.setMouseTracking(True)
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_config(self, config: dict):
        self.config = config
        self.update()

    def _bounding_box(self):
        if not self.monitors:
            return (0, 0, 1, 1)
        min_x = min(m["geometry"][0] for m in self.monitors)
        min_y = min(m["geometry"][1] for m in self.monitors)
        max_x = max(m["geometry"][0] + m["geometry"][2] for m in self.monitors)
        max_y = max(m["geometry"][1] + m["geometry"][3] for m in self.monitors)
        return (min_x, min_y, max_x, max_y)

    def _scale_and_offset(self):
        """Return (scale, offset_x, offset_y) for mapping monitor geometry
        to widget coordinates."""
        bbox = self._bounding_box()
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= 0 or h <= 0:
            return 1.0, self.PADDING, self.PADDING
        avail_w = max(1, self.width() - 2 * self.PADDING)
        avail_h = max(1, self.height() - 2 * self.PADDING)
        s = min(avail_w / w, avail_h / h)
        scaled_w = w * s
        scaled_h = h * s
        ox = (self.width() - scaled_w) / 2 - bbox[0] * s
        oy = (self.height() - scaled_h) / 2 - bbox[1] * s
        return s, ox, oy

    def _monitor_rect(self, monitor) -> QRect:
        s, ox, oy = self._scale_and_offset()
        gx, gy, gw, gh = monitor["geometry"]
        return QRect(int(gx * s + ox), int(gy * s + oy),
                     int(gw * s), int(gh * s))

    def _handle_rects(self, monitor) -> dict:
        r = self._monitor_rect(monitor)
        s = self.HANDLE_SIZE
        h = s // 2
        x = r.x(); y = r.y()
        w = r.width(); ht = r.height()
        cx = x + w // 2
        cy = y + ht // 2
        return {
            "TopLeft":     QRect(x - h, y - h, s, s),
            "Top":         QRect(cx - h, y - h, s, s),
            "TopRight":    QRect(x + w - h, y - h, s, s),
            "Left":        QRect(x - h, cy - h, s, s),
            "Right":       QRect(x + w - h, cy - h, s, s),
            "BottomLeft":  QRect(x - h, y + ht - h, s, s),
            "Bottom":      QRect(cx - h, y + ht - h, s, s),
            "BottomRight": QRect(x + w - h, y + ht - h, s, s),
        }

    def _is_configured(self, monitor_name: str, pos_id: str) -> bool:
        mon = self.config.get("monitors", {}).get(monitor_name, {})
        binding = mon.get(pos_id, {})
        action = binding.get("action", {})
        return action.get("type", "none") != "none"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pal = self.palette()
        text_col = pal.color(QPalette.ColorRole.Text)
        mid_col = pal.color(QPalette.ColorRole.Mid)
        base_col = pal.color(QPalette.ColorRole.Base)
        alt_col = pal.color(QPalette.ColorRole.AlternateBase)
        hl_col = pal.color(QPalette.ColorRole.Highlight)
        hl_text_col = pal.color(QPalette.ColorRole.HighlightedText)

        # Draw each monitor + handles
        for monitor in self.monitors:
            rect = self._monitor_rect(monitor)

            # Monitor body
            painter.setPen(QPen(mid_col, 2))
            painter.setBrush(QBrush(base_col))
            painter.drawRoundedRect(rect, 6, 6)

            # Monitor label (model + connector)
            label_text = display_name(monitor)
            geo = monitor["geometry"]
            sub_text = f"{geo[2]}×{geo[3]}"
            font = QFont(painter.font())
            # Scale font down if monitor is small
            pt = max(self.MIN_MONITOR_LABEL_PT, min(12, rect.width() // 30))
            font.setPointSize(pt)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(text_col)
            label_rect = QRect(rect.x() + 8, rect.y() + 8,
                               rect.width() - 16, rect.height() - 16)
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                label_text,
            )
            font.setBold(False)
            font.setPointSize(max(self.MIN_MONITOR_LABEL_PT - 1, pt - 2))
            painter.setFont(font)
            painter.setPen(mid_col)
            sub_rect = QRect(label_rect.x(),
                             label_rect.y() + label_rect.height() // 2 + pt + 4,
                             label_rect.width(), pt + 8)
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                sub_text,
            )

            # Handles (corners + edge midpoints)
            handles = self._handle_rects(monitor)
            for pos_id, h_rect in handles.items():
                is_sel = (self.selected == (monitor["name"], pos_id))
                is_hov = (self.hovered == (monitor["name"], pos_id))
                is_cfg = self._is_configured(monitor["name"], pos_id)

                if is_sel:
                    fill = hl_col
                    border = hl_text_col
                    border_w = 2.0
                elif is_hov:
                    fill = QColor(hl_col); fill.setAlpha(140)
                    border = hl_col
                    border_w = 1.6
                elif is_cfg:
                    fill = QColor(hl_col); fill.setAlpha(180)
                    border = hl_col.darker(115)
                    border_w = 1.4
                else:
                    fill = alt_col
                    border = mid_col
                    border_w = 1.2

                painter.setPen(QPen(border, border_w))
                painter.setBrush(QBrush(fill))
                painter.drawRoundedRect(h_rect, 4, 4)

    def _hit_test(self, pos):
        for monitor in self.monitors:
            handles = self._handle_rects(monitor)
            for pos_id, rect in handles.items():
                if rect.contains(pos):
                    return (monitor["name"], pos_id)
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit_test(event.pos())
        if hit:
            self.selected = hit
            self.cornerSelected.emit(*hit)
            self.update()

    def mouseMoveEvent(self, event):
        hit = self._hit_test(event.pos())
        if hit != self.hovered:
            self.hovered = hit
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if hit
                else Qt.CursorShape.ArrowCursor
            )
            self.update()

    def leaveEvent(self, event):
        if self.hovered is not None:
            self.hovered = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def select(self, monitor_name, pos_id):
        self.selected = (monitor_name, pos_id)
        self.update()

    def select_first(self):
        if self.monitors:
            self.selected = (self.monitors[0]["name"], "TopLeft")
            self.cornerSelected.emit(*self.selected)
            self.update()


# -----------------------------------------------------------------------------
# Action editor — inline form for one corner/edge
# -----------------------------------------------------------------------------
class ActionEditor(QWidget):
    """Editor for one action. Emits actionChanged whenever the user edits."""

    actionChanged = pyqtSignal(dict)

    def __init__(self, action: dict, parent=None):
        super().__init__(parent)
        self._suppress_signals = False
        self._draft_actions = {
            "none": dict(NONE_ACTION),
            "shortcut": dict(DEFAULT_SHORTCUT_ACTION),
            "command": dict(DEFAULT_COMMAND_ACTION),
        }
        self.action = dict(NONE_ACTION)
        self._build_ui()
        self.set_action(action)

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.type_combo = QComboBox()
        self.type_combo.addItem(_("No action"), "none")
        self.type_combo.addItem(_("Trigger shortcut"), "shortcut")
        self.type_combo.addItem(_("Command"), "command")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addRow(_("Action:"), self.type_combo)

        self.shortcut_combo = QComboBox()
        for comp, name, label in builtin_shortcuts():
            self.shortcut_combo.addItem(label, (comp, name))
        self.shortcut_combo.addItem(_("Custom shortcut…"), ("__custom__", ""))
        self.shortcut_combo.currentIndexChanged.connect(self._on_shortcut_changed)
        layout.addRow(_("Shortcut:"), self.shortcut_combo)
        self._shortcut_row_label = layout.labelForField(self.shortcut_combo)

        self.custom_component = QLineEdit()
        self.custom_component.setPlaceholderText(_("e.g. kwin"))
        self.custom_component.textChanged.connect(self._on_custom_changed)
        layout.addRow(_("Component:"), self.custom_component)
        self._component_row_label = layout.labelForField(self.custom_component)

        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText(_("e.g. Overview"))
        self.custom_name.textChanged.connect(self._on_custom_changed)
        layout.addRow(_("Shortcut name:"), self.custom_name)
        self._name_row_label = layout.labelForField(self.custom_name)

        self.command_program = QLineEdit()
        self.command_program.textChanged.connect(self._on_command_changed)
        layout.addRow(_("Program"), self.command_program)
        self._command_program_label = layout.labelForField(self.command_program)

        self.command_arguments = QListWidget()
        self.command_arguments.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addRow(_("Arguments"), self.command_arguments)
        self._command_arguments_label = layout.labelForField(self.command_arguments)

        command_buttons_wrap = QWidget()
        command_buttons = QHBoxLayout(command_buttons_wrap)
        command_buttons.setContentsMargins(0, 0, 0, 0)
        command_buttons.setSpacing(6)

        self.arg_add_btn = QPushButton(_("Add"))
        self.arg_edit_btn = QPushButton(_("Edit"))
        self.arg_remove_btn = QPushButton(_("Remove"))
        self.arg_up_btn = QPushButton(_("Move Up"))
        self.arg_down_btn = QPushButton(_("Move Down"))

        self.arg_add_btn.clicked.connect(self._on_add_argument)
        self.arg_edit_btn.clicked.connect(self._on_edit_argument)
        self.arg_remove_btn.clicked.connect(self._remove_selected_argument)
        self.arg_up_btn.clicked.connect(self._move_argument_up)
        self.arg_down_btn.clicked.connect(self._move_argument_down)

        for button in (
            self.arg_add_btn,
            self.arg_edit_btn,
            self.arg_remove_btn,
            self.arg_up_btn,
            self.arg_down_btn,
        ):
            command_buttons.addWidget(button)
        command_buttons.addStretch(1)
        layout.addRow("", command_buttons_wrap)
        self._command_buttons_row = command_buttons_wrap

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid); font-size: 10pt;")
        layout.addRow(self.hint)

    def _update_shortcut_widgets_from_action(self, action: dict):
        comp = action.get("component", "kwin")
        name = action.get("name", "")

        matched = False
        for i in range(self.shortcut_combo.count()):
            data = self.shortcut_combo.itemData(i)
            if data == (comp, name):
                self.shortcut_combo.setCurrentIndex(i)
                matched = True
                break

        if not matched:
            custom_idx = self.shortcut_combo.findData(("__custom__", ""))
            if custom_idx >= 0:
                self.shortcut_combo.setCurrentIndex(custom_idx)

        self.custom_component.setText(comp)
        self.custom_name.setText(name)

    def _update_command_widgets_from_action(self, action: dict):
        self.command_program.setText(action.get("program", ""))
        self.command_arguments.clear()
        for argument in action.get("arguments", []):
            self.command_arguments.addItem(argument)

    def _populate_from_current_type(self):
        self._suppress_signals = True
        atype = self.type_combo.currentData() or "none"
        current = _clone_action(self._draft_actions.get(atype, {"type": atype}))

        if atype == "shortcut":
            self._update_shortcut_widgets_from_action(current)
        elif atype == "command":
            self._update_command_widgets_from_action(current)

        self.action = current
        self._suppress_signals = False
        self._update_visibility()

    def _emit(self):
        if not self._suppress_signals:
            self.actionChanged.emit(_clone_action(self.action))

    def _sync_shortcut_action_from_widgets(self):
        data = self.shortcut_combo.currentData()
        if not data:
            return

        comp, name = data
        if comp == "__custom__":
            comp = self.custom_component.text().strip() or "kwin"
            name = self.custom_name.text().strip()

        canonical = {
            "type": "shortcut",
            "component": comp,
            "name": name,
        }
        previous = self._draft_actions.get("shortcut")
        self.action = _merge_action_extensions(previous, canonical)
        self._draft_actions["shortcut"] = _clone_action(self.action)

    def _sync_command_action_from_widgets(self):
        arguments = [
            self.command_arguments.item(i).text()
            for i in range(self.command_arguments.count())
        ]
        previous = self._draft_actions.get("command")
        self.action = _command_action_from_editor(
            self.command_program.text(),
            arguments,
            previous,
        )
        self._draft_actions["command"] = _clone_action(self.action)

    def _on_type_changed(self):
        if self._suppress_signals:
            return

        self._populate_from_current_type()
        atype = self.type_combo.currentData()
        self.action = _clone_action(self._draft_actions.get(atype, dict(NONE_ACTION)))
        self._emit()

    def _on_shortcut_changed(self):
        if self._suppress_signals:
            return
        self._sync_shortcut_action_from_widgets()
        self._update_visibility()
        self._emit()

    def _on_custom_changed(self):
        if self._suppress_signals:
            return
        if self.shortcut_combo.currentData() == ("__custom__", ""):
            self._sync_shortcut_action_from_widgets()
            self._emit()

    def _add_argument_value(self, value: str):
        self.command_arguments.addItem(value)
        self.command_arguments.setCurrentRow(self.command_arguments.count() - 1)
        self._sync_command_action_from_widgets()
        self._emit()

    def _edit_selected_argument_value(self, value: str):
        row = self.command_arguments.currentRow()
        if row < 0:
            return
        self.command_arguments.item(row).setText(value)
        self._sync_command_action_from_widgets()
        self._emit()

    def _remove_selected_argument(self):
        row = self.command_arguments.currentRow()
        if row < 0:
            return
        self.command_arguments.takeItem(row)
        if row >= self.command_arguments.count():
            row = self.command_arguments.count() - 1
        if row >= 0:
            self.command_arguments.setCurrentRow(row)
        self._sync_command_action_from_widgets()
        self._emit()

    def _move_argument_up(self):
        row = self.command_arguments.currentRow()
        if row <= 0:
            return
        item = self.command_arguments.takeItem(row)
        self.command_arguments.insertItem(row - 1, item)
        self.command_arguments.setCurrentRow(row - 1)
        self._sync_command_action_from_widgets()
        self._emit()

    def _move_argument_down(self):
        row = self.command_arguments.currentRow()
        if row < 0 or row >= self.command_arguments.count() - 1:
            return
        item = self.command_arguments.takeItem(row)
        self.command_arguments.insertItem(row + 1, item)
        self.command_arguments.setCurrentRow(row + 1)
        self._sync_command_action_from_widgets()
        self._emit()

    def _on_add_argument(self):
        value, ok = QInputDialog.getText(self, _("Argument"), _("Enter argument value:"))
        if ok:
            self._add_argument_value(value)

    def _on_edit_argument(self):
        row = self.command_arguments.currentRow()
        if row < 0:
            return
        current_value = self.command_arguments.item(row).text()
        value, ok = QInputDialog.getText(
            self,
            _("Argument"),
            _("Enter argument value:"),
            text=current_value,
        )
        if ok:
            self._edit_selected_argument_value(value)

    def _on_command_changed(self):
        if self._suppress_signals:
            return
        self._sync_command_action_from_widgets()
        self._emit()

    def _update_visibility(self):
        atype = self.type_combo.currentData()
        is_shortcut = (atype == "shortcut")
        is_custom = is_shortcut and (
            self.shortcut_combo.currentData() == ("__custom__", "")
        )
        is_command = (atype == "command")

        self.shortcut_combo.setVisible(is_shortcut)
        self._shortcut_row_label.setVisible(is_shortcut)
        self.custom_component.setVisible(is_custom)
        self._component_row_label.setVisible(is_custom)
        self.custom_name.setVisible(is_custom)
        self._name_row_label.setVisible(is_custom)

        self.command_program.setVisible(is_command)
        self._command_program_label.setVisible(is_command)
        self.command_arguments.setVisible(is_command)
        self._command_arguments_label.setVisible(is_command)
        self._command_buttons_row.setVisible(is_command)

        if atype == "none":
            self.hint.setText(_(
                "Pushing the cursor against this corner/edge does nothing."
            ))
        elif is_custom:
            self.hint.setText(_(
                "Find shortcut names with: "
                "<code>qdbus6 org.kde.kglobalaccel "
                "/component/&lt;component&gt; "
                "org.kde.kglobalaccel.Component.shortcutNames</code>"
            ))
        elif is_command:
            self.hint.setText(_(
                "Command action runs the program with argv items exactly as listed."
            ))
        else:
            self.hint.setText(_(
                "The selected shortcut will be invoked when the cursor "
                "is pushed against this corner/edge."
            ))

    def set_action(self, action: dict):
        loaded = _clone_action(action)
        atype = loaded.get("type")
        if atype not in {"none", "shortcut", "command"}:
            atype = "none"
            loaded = dict(NONE_ACTION)

        self._draft_actions = {
            "none": dict(NONE_ACTION),
            "shortcut": dict(DEFAULT_SHORTCUT_ACTION),
            "command": dict(DEFAULT_COMMAND_ACTION),
        }
        self._draft_actions[atype] = loaded

        self._suppress_signals = True
        idx = self.type_combo.findData(atype)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self._suppress_signals = False

        self._populate_from_current_type()

    def current_action(self) -> dict:
        return _clone_action(self.action)


# -----------------------------------------------------------------------------
# Main window — canvas on top, editor below
# -----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("Hot Corners Per Monitor"))
        self.setMinimumSize(QSize(900, 700))

        self.monitors = detect_monitors()
        loaded_config = load_config()
        self.config_baseline = loaded_config.baseline
        self.config_valid = loaded_config.document is not None
        self.config = loaded_config.document or normalize_config_to_v2({})
        self.is_v3 = is_v3_document(self.config)
        self.current_selection = None  # (monitor_name, pos_id)
        self.active_context_key = "default" if self.is_v3 else None
        self._local_binding_drafts = {}
        self._suppress_binding_signals = False
        self._suppress_context_signals = False
        self._build_ui()
        # Pre-select first corner so editor has something to show
        if self.monitors:
            self.canvas.select_first()
        if self.is_v3:
            self._refresh_context_selector()
            self._select_context("default", reload_binding=False)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Banner
        banner = QLabel(_(
            "<b>Tip:</b> Disable the standard KDE hot corners in "
            "System Settings → Screen Edges before relying on this script, "
            "otherwise both will fire."
        ))
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background: palette(alternate-base); "
            "padding: 10px; border-bottom: 1px solid palette(mid);"
        )
        outer.addWidget(banner)

        # Body
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)

        canvas_header = QLabel(_(
            "Monitor arrangement — click a corner or edge to configure"
        ))
        canvas_header.setStyleSheet("font-weight: bold;")
        body_layout.addWidget(canvas_header)

        self.canvas = MonitorCanvas(self.monitors, self._canvas_config())
        self.canvas.cornerSelected.connect(self._on_corner_selected)
        body_layout.addWidget(self.canvas, 2)

        # Editor box
        self.editor_box = QGroupBox(_("Select a corner above"))
        editor_layout = QVBoxLayout(self.editor_box)
        editor_layout.setContentsMargins(12, 12, 12, 12)

        if self.is_v3:
            context_row = QHBoxLayout()
            self.context_combo = QComboBox()
            self.context_combo.currentIndexChanged.connect(self._on_context_combo_changed)
            context_row.addWidget(self.context_combo, 1)

            self.add_context_btn = QPushButton(_("Add Context"))
            self.edit_context_btn = QPushButton(_("Edit Context"))
            self.remove_context_btn = QPushButton(_("Remove Context"))
            self.add_context_btn.clicked.connect(self._on_add_context)
            self.edit_context_btn.clicked.connect(self._on_edit_context)
            self.remove_context_btn.clicked.connect(self._on_remove_context)
            context_row.addWidget(self.add_context_btn)
            context_row.addWidget(self.edit_context_btn)
            context_row.addWidget(self.remove_context_btn)
            editor_layout.addLayout(context_row)

            self.binding_state_combo = QComboBox()
            self.binding_state_combo.currentIndexChanged.connect(self._on_binding_state_changed)
            editor_layout.addWidget(self.binding_state_combo)
        else:
            self.context_combo = None
            self.add_context_btn = None
            self.edit_context_btn = None
            self.remove_context_btn = None
            self.binding_state_combo = None

        if self.is_v3:
            tap_group = QGroupBox(_("Tap"))
            tap_layout = QVBoxLayout(tap_group)
            self.action_editor = ActionEditor(dict(NONE_ACTION))
            self.action_editor.actionChanged.connect(self._on_action_changed)
            tap_layout.addWidget(self.action_editor)
            editor_layout.addWidget(tap_group)

            linger_group = QGroupBox(_("Linger"))
            linger_layout = QVBoxLayout(linger_group)
            self.linger_action_editor = ActionEditor(dict(NONE_ACTION))
            self.linger_action_editor.actionChanged.connect(self._on_linger_action_changed)
            linger_layout.addWidget(self.linger_action_editor)

            linger_delay_row = QHBoxLayout()
            linger_delay_label = QLabel(_("Linger delay"))
            self.linger_delay_spin = QSpinBox()
            self.linger_delay_spin.setMinimum(MIN_LINGER_MS)
            self.linger_delay_spin.setMaximum(MAX_LINGER_MS)
            self.linger_delay_spin.setSingleStep(50)
            self.linger_delay_spin.setSuffix(" ms")
            self.linger_delay_spin.setToolTip(_(
                "Time the cursor must stay before the linger action runs instead of the tap action."
            ))
            self.linger_delay_spin.valueChanged.connect(self._on_linger_delay_changed)
            linger_delay_row.addWidget(linger_delay_label)
            linger_delay_row.addWidget(self.linger_delay_spin)
            linger_delay_row.addStretch(1)
            linger_layout.addLayout(linger_delay_row)

            editor_layout.addWidget(linger_group)
        else:
            # Legacy (v1/v2) bindings have no tap/linger distinction — keep
            # the previous neutral presentation instead of the v3 grouping.
            self.action_editor = ActionEditor(dict(NONE_ACTION))
            self.action_editor.actionChanged.connect(self._on_action_changed)
            editor_layout.addWidget(self.action_editor)
            self.linger_action_editor = None
            self.linger_delay_spin = None

        cooldown_row = QHBoxLayout()
        cooldown_label = QLabel(_("Cooldown"))
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setMinimum(0)
        self.cooldown_spin.setMaximum(MAX_COOLDOWN_MS)
        self.cooldown_spin.setSingleStep(50)
        self.cooldown_spin.setSuffix(" ms")
        self.cooldown_spin.setToolTip(_("Minimum time before this hot zone can trigger again."))
        self.cooldown_spin.valueChanged.connect(self._on_cooldown_changed)
        cooldown_row.addWidget(cooldown_label)
        cooldown_row.addWidget(self.cooldown_spin)
        cooldown_row.addStretch(1)
        editor_layout.addLayout(cooldown_row)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidget(self.editor_box)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body_layout.addWidget(self.editor_scroll, 3)

        outer.addWidget(body, 1)

        # Bottom buttons
        button_wrap = QFrame()
        button_wrap.setStyleSheet(
            "border-top: 1px solid palette(mid); padding: 8px;"
        )
        bl = QHBoxLayout(button_wrap)

        buttons = QDialogButtonBox()
        if self.is_v3:
            self.upgrade_button = None
        else:
            # Only offered for a legacy document, and only ever applied after
            # explicit confirmation -- opening the GUI never upgrades.
            self.upgrade_button = buttons.addButton(
                _("Enable tap/linger and contexts…"),
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            self.upgrade_button.setToolTip(_(
                "Upgrade this configuration so each hot zone can have a "
                "separate tap and linger action, and so bindings can differ "
                "per activity and virtual desktop. Your existing actions and "
                "cooldowns are kept exactly as they are."
            ))
            self.upgrade_button.clicked.connect(self._on_upgrade_to_v3)
        self.reset_btn = buttons.addButton(
            _("Reload from disk"), QDialogButtonBox.ButtonRole.ResetRole
        )
        self.close_btn = buttons.addButton(
            _("Close"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.apply_btn = buttons.addButton(
            _("Apply"), QDialogButtonBox.ButtonRole.ApplyRole
        )
        self.apply_btn.clicked.connect(self._on_apply)
        self.reset_btn.clicked.connect(self._on_reset)
        self.close_btn.clicked.connect(self.close)

        bl.addWidget(buttons)
        outer.addWidget(button_wrap)

    def _on_upgrade_to_v3(self):
        if self.is_v3 or not self.config_valid:
            return

        answer = QMessageBox.question(
            self,
            _("Enable tap/linger and contexts?"),
            _(
                "This upgrades your configuration so that each hot zone can "
                "have a separate tap action and linger action, and so that "
                "bindings can differ per activity and per virtual desktop.\n\n"
                "What is kept: every action you have configured, and every "
                "cooldown value, exactly as they are. They become the "
                "\"Default\" context, which applies whenever no more specific "
                "context matches.\n\n"
                "What changes: the configuration is stored in a newer format. "
                "Nothing is written until you choose Apply, and older versions "
                "of this tool will not read the new format.\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            upgraded = migrate_config_v2_to_v3(self.config)
        except InvalidConfig as error:
            QMessageBox.critical(
                self, _("Upgrade failed"),
                _(
                    "The configuration could not be upgraded, so nothing was "
                    "changed. Details: {detail}"
                ).format(detail=str(error)),
            )
            return

        selection = self.current_selection
        self.config = upgraded
        self.is_v3 = True
        self.active_context_key = "default"
        self._local_binding_drafts = {}
        self._rebuild_editor()

        if selection:
            self.canvas.select(*selection)
            self._on_corner_selected(*selection)
        elif self.monitors:
            self.canvas.select_first()

    def _rebuild_editor(self):
        """Rebuild the editor after the document's schema version changed."""
        self._suppress_binding_signals = True
        self._suppress_context_signals = True
        try:
            self._build_ui()
        finally:
            self._suppress_binding_signals = False
            self._suppress_context_signals = False

        if self.is_v3:
            self._refresh_context_selector()
            self._select_context(self.active_context_key, reload_binding=False)

    def _canvas_config(self):
        if not self.is_v3:
            return self.config
        monitors = {}
        context = get_context_entry(self.config, self.active_context_key)
        if isinstance(context, dict):
            monitors = context.get("monitors", {})
            if not isinstance(monitors, dict):
                monitors = {}
        return {"monitors": monitors}

    def _refresh_context_selector(self):
        if not self.is_v3:
            return
        self._suppress_context_signals = True
        self.context_combo.clear()
        contexts = self.config.get("contexts", {})
        for key in ordered_context_keys(contexts):
            self.context_combo.addItem(
                context_display_label(key, contexts.get(key)),
                key,
            )
        if self.active_context_key is not None:
            idx = self.context_combo.findData(self.active_context_key)
            if idx >= 0:
                self.context_combo.setCurrentIndex(idx)
        self._suppress_context_signals = False
        self._update_context_buttons()

    def _update_context_buttons(self):
        if not self.is_v3:
            return
        is_default = self.active_context_key == "default"
        self.edit_context_btn.setEnabled(not is_default)
        self.remove_context_btn.setEnabled(not is_default)

    def _populate_binding_state_combo(self, state: str):
        if not self.is_v3:
            return
        self._suppress_binding_signals = True
        self.binding_state_combo.clear()
        if self.active_context_key != "default":
            self.binding_state_combo.addItem(_("Inherit from Default"), V3_BINDING_INHERIT)
        self.binding_state_combo.addItem(_("No action"), V3_BINDING_NONE)
        self.binding_state_combo.addItem(_("Trigger shortcut"), "shortcut")
        self.binding_state_combo.addItem(_("Command"), "command")
        idx = self.binding_state_combo.findData(state)
        if idx >= 0:
            self.binding_state_combo.setCurrentIndex(idx)
        self._suppress_binding_signals = False

    def _set_v3_controls_enabled(self, enabled: bool):
        self.action_editor.setEnabled(enabled)
        self.linger_action_editor.setEnabled(enabled)
        self.linger_delay_spin.setEnabled(enabled)
        self.cooldown_spin.setEnabled(enabled)
        self.edit_context_btn.setEnabled(enabled and self.active_context_key != "default")
        self.remove_context_btn.setEnabled(enabled and self.active_context_key != "default")

    def _active_context_kind(self) -> str:
        if not self.is_v3:
            return ""
        entry = get_context_entry(self.config, self.active_context_key)
        if not isinstance(entry, dict):
            return ""
        return entry.get("kind", "")

    def _select_context(self, context_key: str, *, reload_binding: bool = True):
        if not self.is_v3:
            return
        contexts = self.config.get("contexts", {})
        if not isinstance(contexts, dict) or context_key not in contexts:
            return
        self.active_context_key = context_key
        self._refresh_context_selector()
        self.canvas.set_config(self._canvas_config())
        self._update_context_buttons()
        if reload_binding and self.current_selection:
            mon, pos = self.current_selection
            self._load_v3_binding(mon, pos)

    def _on_context_combo_changed(self, index: int):
        if self._suppress_context_signals or not self.is_v3:
            return
        context_key = self.context_combo.itemData(index)
        if isinstance(context_key, str):
            self._select_context(context_key)

    def _on_binding_state_changed(self, index: int):
        if self._suppress_binding_signals or not self.is_v3:
            return
        if not self.current_selection or not self.config_valid:
            return

        state = self.binding_state_combo.itemData(index)
        if not isinstance(state, str):
            return

        monitor_name, position_id = self.current_selection
        draft_key = (self.active_context_key, monitor_name, position_id)
        existing = get_context_binding(self.config, self.active_context_key, monitor_name, position_id)

        if state == V3_BINDING_INHERIT and self.active_context_key != "default":
            if isinstance(existing, dict):
                self._local_binding_drafts[draft_key] = copy.deepcopy(existing)
            remove_v3_binding(self.config, self.active_context_key, monitor_name, position_id)
            preview = get_default_v3_binding(self.config, monitor_name, position_id)
            if not isinstance(preview, dict):
                preview = {"tap": dict(NONE_ACTION), "cooldownMs": DEFAULT_COOLDOWN_MS}
            self._suppress_binding_signals = True
            self.action_editor.set_action(preview.get("tap", dict(NONE_ACTION)))
            self.linger_action_editor.set_action(preview.get("linger", dict(NONE_ACTION)))
            self.linger_delay_spin.setValue(normalize_linger_ms(preview.get("lingerMs", DEFAULT_LINGER_MS)))
            self.cooldown_spin.setValue(normalize_cooldown_ms(preview.get("cooldownMs", DEFAULT_COOLDOWN_MS), DEFAULT_COOLDOWN_MS))
            self._suppress_binding_signals = False
            self._set_v3_controls_enabled(False)
            self.canvas.set_config(self._canvas_config())
            return

        draft = self._local_binding_drafts.get(draft_key)
        if not isinstance(draft, dict):
            draft = existing if isinstance(existing, dict) else None

        if state == V3_BINDING_NONE:
            tap = dict(NONE_ACTION)
        elif state == "command":
            tap = draft.get("tap") if isinstance(draft, dict) and draft.get("tap", {}).get("type") == "command" else dict(DEFAULT_COMMAND_ACTION)
        else:
            tap = draft.get("tap") if isinstance(draft, dict) and draft.get("tap", {}).get("type") == "shortcut" else dict(DEFAULT_SHORTCUT_ACTION)

        cooldown_value = DEFAULT_COOLDOWN_MS
        if isinstance(draft, dict):
            cooldown_value = normalize_cooldown_ms(draft.get("cooldownMs", DEFAULT_COOLDOWN_MS), DEFAULT_COOLDOWN_MS)

        linger_action = draft.get("linger") if isinstance(draft, dict) else None
        linger_ms_value = DEFAULT_LINGER_MS
        if isinstance(draft, dict):
            linger_ms_value = normalize_linger_ms(draft.get("lingerMs", DEFAULT_LINGER_MS))

        try:
            binding = create_v3_binding(tap, cooldown_value, draft, linger_action, linger_ms_value)
        except InvalidConfig:
            binding = create_v3_binding(dict(NONE_ACTION), DEFAULT_COOLDOWN_MS, draft, linger_action, linger_ms_value)
        set_v3_binding(self.config, self.active_context_key, monitor_name, position_id, binding)
        self._local_binding_drafts[draft_key] = copy.deepcopy(binding)
        self._suppress_binding_signals = True
        self.action_editor.set_action(binding.get("tap", dict(NONE_ACTION)))
        self.linger_action_editor.set_action(binding.get("linger", dict(NONE_ACTION)))
        self.linger_delay_spin.setValue(binding.get("lingerMs", DEFAULT_LINGER_MS))
        self.cooldown_spin.setValue(binding.get("cooldownMs", DEFAULT_COOLDOWN_MS))
        self._suppress_binding_signals = False
        self._set_v3_controls_enabled(True)
        self.canvas.set_config(self._canvas_config())

    def _current_context_entry(self):
        if not self.is_v3:
            return None
        return get_context_entry(self.config, self.active_context_key)

    def _context_dialog_defaults(self):
        entry = self._current_context_entry() or {}
        return (
            entry.get("kind", "activity"),
            entry.get("activityId", ""),
            entry.get("desktopId", ""),
        )

    def _refresh_context_after_edit(self, context_key: str):
        if not self.is_v3:
            return
        self._refresh_context_selector()
        self._select_context(context_key, reload_binding=True)

    def _on_add_context(self):
        if not self.is_v3 or not self.config_valid:
            return

        dialog = ContextDialog(self, kind="activity")
        if int(dialog.exec()) != int(QDialog.DialogCode.Accepted):
            return

        kind = dialog.context_kind()
        activity_id = dialog.activity_id()
        desktop_id = dialog.desktop_id()
        if kind == "activity":
            desktop_id = None
        elif kind == "desktop":
            activity_id = None
        try:
            key, entry = build_context_entry(kind, activity_id, desktop_id, {"monitors": {}})
        except InvalidConfig:
            QMessageBox.critical(self, _("Save failed"), _("Invalid context identifier."))
            return

        contexts = self.config.setdefault("contexts", {})
        if key in contexts:
            QMessageBox.critical(self, _("Save failed"), _("A context with this identifier already exists."))
            return

        contexts[key] = entry
        self._refresh_context_after_edit(key)

    def _on_edit_context(self):
        if not self.is_v3 or not self.config_valid:
            return
        if self.active_context_key == "default":
            return

        entry = self._current_context_entry()
        if not isinstance(entry, dict):
            return

        dialog = ContextDialog(
            self,
            kind=entry.get("kind", "activity"),
            activity_id=entry.get("activityId", ""),
            desktop_id=entry.get("desktopId", ""),
        )
        if int(dialog.exec()) != int(QDialog.DialogCode.Accepted):
            return

        kind = dialog.context_kind()
        activity_id = dialog.activity_id()
        desktop_id = dialog.desktop_id()
        if kind == "activity":
            desktop_id = None
        elif kind == "desktop":
            activity_id = None
        try:
            new_key, new_entry = build_context_entry(kind, activity_id, desktop_id, entry)
        except InvalidConfig:
            QMessageBox.critical(self, _("Save failed"), _("Invalid context identifier."))
            return

        contexts = self.config.setdefault("contexts", {})
        if new_key != self.active_context_key and new_key in contexts:
            QMessageBox.critical(self, _("Save failed"), _("A context with this identifier already exists."))
            return

        set_context_entry(self.config, self.active_context_key, new_key, new_entry)
        self._refresh_context_after_edit(new_key)

    def _on_remove_context(self):
        if not self.is_v3 or not self.config_valid:
            return
        if self.active_context_key == "default":
            QMessageBox.critical(self, _("Save failed"), _("The default context cannot be removed."))
            return
        result = QMessageBox.question(
            self,
            _("Remove Context"),
            _("Remove this context?"),
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        remove_context_entry(self.config, self.active_context_key)
        self.active_context_key = "default"
        self._refresh_context_selector()
        self._select_context("default", reload_binding=True)

    def _load_v3_binding(self, monitor_name: str, position_id: str):
        exact = get_context_binding(self.config, self.active_context_key, monitor_name, position_id)
        if self.active_context_key != "default" and not isinstance(exact, dict):
            preview = get_default_v3_binding(self.config, monitor_name, position_id)
            state = V3_BINDING_INHERIT if isinstance(preview, dict) else V3_BINDING_INHERIT
            binding = preview if isinstance(preview, dict) else {"tap": dict(NONE_ACTION), "cooldownMs": DEFAULT_COOLDOWN_MS}
            self._populate_binding_state_combo(state)
            self._suppress_binding_signals = True
            self.action_editor.set_action(binding.get("tap", dict(NONE_ACTION)))
            self.linger_action_editor.set_action(binding.get("linger", dict(NONE_ACTION)))
            self.linger_delay_spin.setValue(normalize_linger_ms(binding.get("lingerMs", DEFAULT_LINGER_MS)))
            self.cooldown_spin.setValue(normalize_cooldown_ms(binding.get("cooldownMs", DEFAULT_COOLDOWN_MS), DEFAULT_COOLDOWN_MS))
            self._suppress_binding_signals = False
            self._set_v3_controls_enabled(False)
            return

        if not isinstance(exact, dict):
            exact = {"tap": dict(NONE_ACTION), "cooldownMs": DEFAULT_COOLDOWN_MS}

        tap = exact.get("tap", dict(NONE_ACTION))
        state = determine_v3_binding_state(self.config, self.active_context_key, monitor_name, position_id)
        if state == V3_BINDING_INHERIT:
            preview = get_default_v3_binding(self.config, monitor_name, position_id)
            if isinstance(preview, dict):
                tap = preview.get("tap", dict(NONE_ACTION))
                exact = preview
        self._populate_binding_state_combo(state if state in {V3_BINDING_INHERIT, V3_BINDING_NONE, "shortcut", "command"} else V3_BINDING_NONE)
        self._suppress_binding_signals = True
        self.action_editor.set_action(tap)
        self.linger_action_editor.set_action(exact.get("linger", dict(NONE_ACTION)))
        self.linger_delay_spin.setValue(normalize_linger_ms(exact.get("lingerMs", DEFAULT_LINGER_MS)))
        self.cooldown_spin.setValue(normalize_cooldown_ms(exact.get("cooldownMs", DEFAULT_COOLDOWN_MS), DEFAULT_COOLDOWN_MS))
        self._suppress_binding_signals = False
        self._set_v3_controls_enabled(state != V3_BINDING_INHERIT or self.active_context_key == "default")

    def _current_binding(self):
        if not self.current_selection:
            return None
        monitor_name, position_id = self.current_selection
        if self.is_v3:
            return get_context_binding(self.config, self.active_context_key, monitor_name, position_id)
        return self.config["monitors"].get(monitor_name, {}).get(position_id)

    def _ensure_current_binding(self):
        if not self.current_selection:
            return None
        monitor_name, position_id = self.current_selection
        if self.is_v3:
            if self.active_context_key != "default" and self.binding_state_combo and self.binding_state_combo.currentData() == V3_BINDING_INHERIT:
                return None
            preserved = self._local_binding_drafts.get((self.active_context_key, monitor_name, position_id))
            binding = get_context_binding(self.config, self.active_context_key, monitor_name, position_id)
            if isinstance(binding, dict):
                return binding
            current_state = self.binding_state_combo.currentData() if self.binding_state_combo else "shortcut"
            linger_action = self.linger_action_editor.current_action()
            linger_ms_value = self.linger_delay_spin.value()
            if current_state == V3_BINDING_NONE:
                binding = create_v3_binding(dict(NONE_ACTION), self.cooldown_spin.value(), preserved, linger_action, linger_ms_value)
            elif current_state == "command":
                binding = create_v3_binding(self.action_editor.current_action(), self.cooldown_spin.value(), preserved, linger_action, linger_ms_value)
            else:
                binding = create_v3_binding(self.action_editor.current_action(), self.cooldown_spin.value(), preserved, linger_action, linger_ms_value)
            set_v3_binding(self.config, self.active_context_key, monitor_name, position_id, binding)
            return binding
        monitors = self.config.setdefault("monitors", {})
        monitor = monitors.setdefault(monitor_name, {})
        binding = monitor.get(position_id)
        if isinstance(binding, dict):
            return binding

        try:
            binding = create_v2_binding(self.action_editor.current_action())
        except InvalidConfig:
            binding = {
                "action": _clone_action(self.action_editor.current_action()),
                "cooldownMs": DEFAULT_COOLDOWN_MS,
            }
        monitor[position_id] = binding
        return binding

    def _set_cooldown_widget(self, value):
        self._suppress_binding_signals = True
        self.cooldown_spin.setValue(int(value))
        self._suppress_binding_signals = False

    def _on_corner_selected(self, monitor_name, position_id):
        self.current_selection = (monitor_name, position_id)
        mon = next(
            (m for m in self.monitors if m["name"] == monitor_name), None
        )
        if not mon:
            return
        pos_label = position_label(position_id)
        if self.is_v3:
            self.editor_box.setTitle(
                _("{position} of {monitor}").format(
                    position=pos_label, monitor=display_name(mon)
                )
            )
            self._load_v3_binding(monitor_name, position_id)
            self.canvas.set_config(self._canvas_config())
            return
        self.editor_box.setTitle(
            _("{position} of {monitor}").format(
                position=pos_label, monitor=display_name(mon)
            )
        )
        binding = self.config["monitors"].get(monitor_name, {}).get(
            position_id, {}
        )
        action = binding.get("action", dict(NONE_ACTION))
        cooldown_value = binding.get("cooldownMs", DEFAULT_COOLDOWN_MS)
        cooldown_value = normalize_cooldown_ms(cooldown_value, DEFAULT_COOLDOWN_MS)

        self._suppress_binding_signals = True
        self.action_editor.set_action(action)
        self.cooldown_spin.setValue(cooldown_value)
        self._suppress_binding_signals = False

    def _on_action_changed(self, action: dict):
        if self._suppress_binding_signals:
            return
        if not self.current_selection or not self.config_valid:
            return

        if self.is_v3:
            if self.binding_state_combo and self.binding_state_combo.currentData() == V3_BINDING_INHERIT and self.active_context_key != "default":
                return
            current_state = self.binding_state_combo.currentData() if self.binding_state_combo else None
            if current_state == V3_BINDING_INHERIT:
                current_state = action.get("type", "none")
            if current_state not in {V3_BINDING_NONE, "shortcut", "command"}:
                current_state = action.get("type", "none")
            if current_state == V3_BINDING_NONE:
                action = dict(NONE_ACTION)
            binding = self._ensure_current_binding()
            if binding is None:
                return
            preserved = copy.deepcopy(binding)
            preserved["tap"] = _clone_action(action)
            preserved["cooldownMs"] = normalize_cooldown_ms(
                preserved.get("cooldownMs", DEFAULT_COOLDOWN_MS),
                DEFAULT_COOLDOWN_MS,
            )
            set_v3_binding(self.config, self.active_context_key, *self.current_selection, preserved)
            self._local_binding_drafts[(self.active_context_key, *self.current_selection)] = copy.deepcopy(preserved)
            desired_state = preserved["tap"].get("type", V3_BINDING_NONE)
            if self.binding_state_combo and self.binding_state_combo.currentData() != desired_state:
                self._suppress_binding_signals = True
                idx = self.binding_state_combo.findData(desired_state)
                if idx >= 0:
                    self.binding_state_combo.setCurrentIndex(idx)
                self._suppress_binding_signals = False
            self.canvas.set_config(self._canvas_config())
            return

        binding = self._ensure_current_binding()
        if binding is None:
            return

        binding["action"] = _clone_action(action)

        current_cooldown = binding.get("cooldownMs", DEFAULT_COOLDOWN_MS)
        binding["cooldownMs"] = normalize_cooldown_ms(current_cooldown, DEFAULT_COOLDOWN_MS)
        self._set_cooldown_widget(binding["cooldownMs"])
        self.canvas.set_config(self.config)

    def _on_cooldown_changed(self, value: int):
        if self._suppress_binding_signals:
            return
        if not self.current_selection or not self.config_valid:
            return

        if self.is_v3:
            if self.binding_state_combo and self.binding_state_combo.currentData() == V3_BINDING_INHERIT and self.active_context_key != "default":
                return
            binding = self._ensure_current_binding()
            if binding is None:
                return
            binding["cooldownMs"] = int(value)
            self._local_binding_drafts[(self.active_context_key, *self.current_selection)] = copy.deepcopy(binding)
            self.canvas.set_config(self._canvas_config())
            return

        binding = self._ensure_current_binding()
        if binding is None:
            return

        binding["cooldownMs"] = int(value)
        self.canvas.set_config(self.config)

    def _on_linger_action_changed(self, action: dict):
        if self._suppress_binding_signals or not self.is_v3:
            return
        if not self.current_selection or not self.config_valid:
            return
        if self.binding_state_combo and self.binding_state_combo.currentData() == V3_BINDING_INHERIT and self.active_context_key != "default":
            return

        binding = self._ensure_current_binding()
        if binding is None:
            return
        preserved = copy.deepcopy(binding)
        preserved["linger"] = _clone_action(action)
        preserved["lingerMs"] = normalize_linger_ms(
            preserved.get("lingerMs", DEFAULT_LINGER_MS),
            DEFAULT_LINGER_MS,
        )
        set_v3_binding(self.config, self.active_context_key, *self.current_selection, preserved)
        self._local_binding_drafts[(self.active_context_key, *self.current_selection)] = copy.deepcopy(preserved)
        self.canvas.set_config(self._canvas_config())

    def _on_linger_delay_changed(self, value: int):
        if self._suppress_binding_signals or not self.is_v3:
            return
        if not self.current_selection or not self.config_valid:
            return
        if self.binding_state_combo and self.binding_state_combo.currentData() == V3_BINDING_INHERIT and self.active_context_key != "default":
            return

        binding = self._ensure_current_binding()
        if binding is None:
            return
        binding["lingerMs"] = int(value)
        self._local_binding_drafts[(self.active_context_key, *self.current_selection)] = copy.deepcopy(binding)
        self.canvas.set_config(self._canvas_config())

    def _validate_config_for_save(self):
        if self.is_v3:
            contexts = self.config.get("contexts", {})
            if not isinstance(contexts, dict) or "default" not in contexts:
                return False, _("Invalid context identifier.")
            for context_key, context in contexts.items():
                if not isinstance(context, dict):
                    continue
                kind = context.get("kind")
                activity_id = context.get("activityId")
                desktop_id = context.get("desktopId")
                ok, _error = validate_context_metadata(kind, activity_id, desktop_id)
                if not ok:
                    return False, _("Invalid context identifier.")
                if context_key != build_context_key(kind, activity_id, desktop_id):
                    return False, _("Invalid context identifier.")
                monitors = context.get("monitors", {})
                if not isinstance(monitors, dict):
                    return False, _("Invalid context identifier.")
                for _monitor_name, monitor in monitors.items():
                    if not isinstance(monitor, dict):
                        continue
                    for _position_id, binding in monitor.items():
                        if _position_id not in POSITION_IDS:
                            continue
                        if not isinstance(binding, dict):
                            continue
                        cooldown_ok, _cooldown_error = validate_cooldown_ms(binding.get("cooldownMs"))
                        if not cooldown_ok:
                            return False, _("Invalid cooldown value.")
                        tap = binding.get("tap")
                        if not isinstance(normalize_action(tap), dict):
                            return False, _("Invalid context identifier.")
                        linger = binding.get("linger")
                        if linger is not None and not isinstance(normalize_action(linger), dict):
                            return False, _("Invalid context identifier.")
                        if "lingerMs" in binding:
                            linger_ms_ok, _linger_ms_error = validate_linger_ms(binding.get("lingerMs"))
                            if not linger_ms_ok:
                                return False, _("Invalid linger delay value.")
            return True, ""
        monitors = self.config.get("monitors", {})
        for _monitor_name, monitor in monitors.items():
            if not isinstance(monitor, dict):
                continue
            for _position_id, binding in monitor.items():
                if _position_id not in POSITION_IDS:
                    continue
                if not isinstance(binding, dict):
                    continue

                cooldown_ok, _cooldown_error = validate_cooldown_ms(binding.get("cooldownMs"))
                if not cooldown_ok:
                    return False, _("Invalid cooldown value.")

                action = binding.get("action")
                if not isinstance(action, dict):
                    continue
                if action.get("type") != "command":
                    continue

                program_ok, _program_error = validate_command_program(action.get("program"))
                if not program_ok:
                    return False, _("Command program cannot be empty.")

                arguments_ok, _arguments_error = validate_command_arguments(action.get("arguments"))
                if not arguments_ok:
                    return False, _("Command arguments are invalid.")
        return True, ""

    def _on_apply(self):
        config = self.config if self.config_valid else None

        valid, error_text = self._validate_config_for_save()
        if not valid:
            QMessageBox.critical(self, _("Save failed"), error_text)
            return

        try:
            updated_baseline = save_config(config, self.config_baseline)
        except ConfigSaveError as error:
            QMessageBox.critical(
                self, _("Save failed"), describe_save_error(error),
            )
            return

        self.config_baseline = updated_baseline
        QMessageBox.information(
            self, _("Saved"),
            _("Configuration saved. KWin has been reloaded — "
              "your changes are active now.")
        )

    def _on_reset(self):
        loaded_config = load_config()
        self.config_baseline = loaded_config.baseline
        self.config_valid = loaded_config.document is not None
        self.config = loaded_config.document or normalize_config_to_v2({})
        self.is_v3 = is_v3_document(self.config)
        self.canvas.set_config(self._canvas_config())
        if self.is_v3:
            self._refresh_context_selector()
        if self.current_selection:
            mon, pos = self.current_selection
            if self.is_v3:
                self._load_v3_binding(mon, pos)
            else:
                binding = self.config["monitors"].get(mon, {}).get(pos, {})
                action = binding.get("action", dict(NONE_ACTION))
                cooldown_value = normalize_cooldown_ms(
                    binding.get("cooldownMs", DEFAULT_COOLDOWN_MS),
                    DEFAULT_COOLDOWN_MS,
                )
                self._suppress_binding_signals = True
                self.action_editor.set_action(action)
                self.cooldown_spin.setValue(cooldown_value)
                self._suppress_binding_signals = False


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("hotcorners-config")
    app.setOrganizationName("flarkAUDIO")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
