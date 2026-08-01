#!/usr/bin/env python3
# Hot Corners Per Monitor — Configuration GUI
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Configuration GUI for the hotcorners-per-monitor KWin script.

Reads/writes the script's config via kreadconfig6/kwriteconfig6, then triggers
a KWin reconfigure so changes take effect immediately.
"""

import gettext
import json
import locale
import os
import subprocess
import sys
from pathlib import Path

from config_schema import (
    create_v2_binding, normalize_config_to_v2,
)
from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal
from PyQt6.QtGui import (
    QGuiApplication, QPainter, QPen, QBrush, QColor, QPalette, QFont,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialogButtonBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

# -----------------------------------------------------------------------------
# i18n setup
# -----------------------------------------------------------------------------
APP_DOMAIN = "hotcorners-config"

def setup_i18n():
    """Initialize gettext using the system locale."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    locale_dirs = [
        Path(__file__).parent / "translations",
        Path("/usr/share/locale"),
        Path.home() / ".local/share/locale",
    ]
    for d in locale_dirs:
        if d.exists():
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

def load_config() -> dict | None:
    """Read and normalize MonitorConfigs without modifying kwinrc."""
    try:
        result = subprocess.run(
            ["kreadconfig6", "--file", "kwinrc",
             "--group", KWINRC_GROUP, "--key", CONFIG_KEY],
            capture_output=True, text=True, check=False,
        )
        raw = result.stdout.strip()
        parsed = json.loads(raw) if raw else {}
        return normalize_config_to_v2(parsed)
    except (json.JSONDecodeError, ValueError, FileNotFoundError):
        return None

def save_config(config: dict | None) -> bool:
    """Write normalized v2 MonitorConfigs and trigger KWin reconfigure."""
    try:
        normalized = normalize_config_to_v2(config)
        payload = json.dumps(normalized, separators=(",", ":"))
        subprocess.run(
            ["kwriteconfig6", "--file", "kwinrc",
             "--group", KWINRC_GROUP, "--key", CONFIG_KEY, payload],
            check=True,
        )
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
            check=False,
        )
        return True
    except (ValueError, TypeError,
            subprocess.CalledProcessError, FileNotFoundError):
        return False

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

def position_label(pos_id: str) -> str:
    for pid, label in POSITION_LAYOUT:
        if pid == pos_id:
            return _(label)
    return pos_id

NONE_ACTION = {"type": "none"}

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
        self.action = dict(action) if action else dict(NONE_ACTION)
        self._suppress_signals = False
        self._build_ui()
        self._populate_from_action()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.type_combo = QComboBox()
        self.type_combo.addItem(_("No action"), "none")
        self.type_combo.addItem(_("Trigger shortcut"), "shortcut")
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

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid); font-size: 10pt;")
        layout.addRow(self.hint)

    def _populate_from_action(self):
        self._suppress_signals = True
        atype = self.action.get("type", "none")
        idx = self.type_combo.findData(atype)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        if atype == "shortcut":
            comp = self.action.get("component", "kwin")
            name = self.action.get("name", "")
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
        self._suppress_signals = False
        self._update_visibility()

    def _emit(self):
        if not self._suppress_signals:
            self.actionChanged.emit(dict(self.action))

    def _on_type_changed(self):
        if self._suppress_signals:
            return
        atype = self.type_combo.currentData()
        if atype == "none":
            self.action = dict(NONE_ACTION)
        else:
            self.action = {"type": "shortcut", "component": "kwin",
                           "name": "Overview"}
            self._populate_from_action()
        self._update_visibility()
        self._emit()

    def _on_shortcut_changed(self):
        if self._suppress_signals:
            return
        data = self.shortcut_combo.currentData()
        if not data:
            return
        comp, name = data
        if comp == "__custom__":
            self._update_visibility()
            self._emit()
            return
        self.action = {"type": "shortcut", "component": comp, "name": name}
        self._suppress_signals = True
        self.custom_component.setText(comp)
        self.custom_name.setText(name)
        self._suppress_signals = False
        self._update_visibility()
        self._emit()

    def _on_custom_changed(self):
        if self._suppress_signals:
            return
        if self.shortcut_combo.currentData() == ("__custom__", ""):
            self.action = {
                "type": "shortcut",
                "component": self.custom_component.text().strip() or "kwin",
                "name": self.custom_name.text().strip(),
            }
            self._emit()

    def _update_visibility(self):
        atype = self.type_combo.currentData()
        is_shortcut = (atype == "shortcut")
        is_custom = is_shortcut and (
            self.shortcut_combo.currentData() == ("__custom__", "")
        )
        self.shortcut_combo.setVisible(is_shortcut)
        self._shortcut_row_label.setVisible(is_shortcut)
        self.custom_component.setVisible(is_custom)
        self._component_row_label.setVisible(is_custom)
        self.custom_name.setVisible(is_custom)
        self._name_row_label.setVisible(is_custom)

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
        else:
            self.hint.setText(_(
                "The selected shortcut will be invoked when the cursor "
                "is pushed against this corner/edge."
            ))

    def set_action(self, action: dict):
        self.action = dict(action) if action else dict(NONE_ACTION)
        self._populate_from_action()

    def current_action(self) -> dict:
        return dict(self.action)


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
        self.config_valid = loaded_config is not None
        self.config = loaded_config or normalize_config_to_v2({})
        self.current_selection = None  # (monitor_name, pos_id)
        self._build_ui()
        # Pre-select first corner so editor has something to show
        if self.monitors:
            self.canvas.select_first()

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

        self.canvas = MonitorCanvas(self.monitors, self.config)
        self.canvas.cornerSelected.connect(self._on_corner_selected)
        body_layout.addWidget(self.canvas, 3)

        # Editor box
        self.editor_box = QGroupBox(_("Select a corner above"))
        editor_layout = QVBoxLayout(self.editor_box)
        editor_layout.setContentsMargins(12, 12, 12, 12)

        self.action_editor = ActionEditor(dict(NONE_ACTION))
        self.action_editor.actionChanged.connect(self._on_action_changed)
        editor_layout.addWidget(self.action_editor)
        body_layout.addWidget(self.editor_box, 2)

        outer.addWidget(body, 1)

        # Bottom buttons
        button_wrap = QFrame()
        button_wrap.setStyleSheet(
            "border-top: 1px solid palette(mid); padding: 8px;"
        )
        bl = QHBoxLayout(button_wrap)

        buttons = QDialogButtonBox()
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

    def _on_corner_selected(self, monitor_name, position_id):
        self.current_selection = (monitor_name, position_id)
        mon = next(
            (m for m in self.monitors if m["name"] == monitor_name), None
        )
        if not mon:
            return
        pos_label = position_label(position_id)
        self.editor_box.setTitle(
            _("{position} of {monitor}").format(
                position=pos_label, monitor=display_name(mon)
            )
        )
        binding = self.config["monitors"].get(monitor_name, {}).get(
            position_id, {}
        )
        action = binding.get("action", dict(NONE_ACTION))
        self.action_editor.set_action(action)

    def _on_action_changed(self, action: dict):
        if not self.current_selection or not self.config_valid:
            return
        monitor_name, position_id = self.current_selection
        monitors = self.config["monitors"]
        if action.get("type", "none") == "none":
            if monitor_name in monitors:
                monitors[monitor_name].pop(position_id, None)
                if not monitors[monitor_name]:
                    monitors.pop(monitor_name, None)
        else:
            monitor = monitors.setdefault(monitor_name, {})
            binding = monitor.get(position_id)
            if binding:
                binding["action"] = dict(action)
            else:
                monitor[position_id] = create_v2_binding(action)
        self.canvas.set_config(self.config)

    def _on_apply(self):
        config = self.config if self.config_valid else None
        if save_config(config):
            QMessageBox.information(
                self, _("Saved"),
                _("Configuration saved. KWin has been reloaded — "
                  "your changes are active now.")
            )
        else:
            QMessageBox.critical(
                self, _("Save failed"),
                _("Could not write the configuration. Check that "
                  "kwriteconfig6 is available on your system.")
            )

    def _on_reset(self):
        loaded_config = load_config()
        self.config_valid = loaded_config is not None
        self.config = loaded_config or normalize_config_to_v2({})
        self.canvas.set_config(self.config)
        if self.current_selection:
            mon, pos = self.current_selection
            binding = self.config["monitors"].get(mon, {}).get(pos, {})
            action = binding.get("action", dict(NONE_ACTION))
            self.action_editor.set_action(action)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("hotcorners-config")
    app.setOrganizationName("flarkAUDIO")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
