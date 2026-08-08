"""Discovery of the KDE activities and virtual desktops a context can target.

Context keys are built from stable runtime identifiers, but only human-readable
names are visible anywhere in Plasma. Without discovery a user has to type an
internal identifier they cannot see, so an override that never matches is easy
to create. This module reads the identifier/name pairs from the supported
read-only D-Bus interfaces:

* activities -- ``org.kde.ActivityManager`` at ``/ActivityManager/Activities``,
  ``ListActivities()`` for the identifiers and ``ActivityName(id)`` for each name.
* virtual desktops -- ``org.kde.KWin`` at ``/VirtualDesktopManager``, the
  ``desktops`` property, which carries ``a(uss)`` entries of
  (position, identifier, name).

PyQt6.QtDBus is already a hard dependency of this project, so it is used here
rather than shelling out and parsing qdbus output.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusReply

ACTIVITY_SERVICE = "org.kde.ActivityManager"
ACTIVITY_PATH = "/ActivityManager/Activities"
ACTIVITY_INTERFACE = "org.kde.ActivityManager.Activities"

KWIN_SERVICE = "org.kde.KWin"
VIRTUAL_DESKTOP_PATH = "/VirtualDesktopManager"
VIRTUAL_DESKTOP_INTERFACE = "org.kde.KWin.VirtualDesktopManager"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"

DBUS_TIMEOUT_MS = 2000

_DEFAULT_BUS = object()


@dataclass(frozen=True)
class ContextOption:
    """One selectable activity or virtual desktop."""

    identifier: str
    name: str


def decode_desktops(raw) -> list[ContextOption]:
    """Decode KWin's ``a(uss)`` desktops property into ordered options.

    Entries are ordered by their reported position. Malformed entries and
    entries without an identifier are skipped rather than surfaced.
    """
    decoded: list[tuple[int, ContextOption]] = []
    if not isinstance(raw, (list, tuple)):
        return []

    for index, entry in enumerate(raw):
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        position, identifier, name = entry[0], entry[1], entry[2]
        if not isinstance(identifier, str) or not identifier:
            continue
        if not isinstance(name, str):
            name = ""
        try:
            sort_key = int(position)
        except (TypeError, ValueError):
            sort_key = index
        decoded.append((sort_key, ContextOption(identifier=identifier, name=name)))

    decoded.sort(key=lambda item: item[0])
    return [option for _position, option in decoded]


def decode_activities(identifiers, name_of) -> list[ContextOption]:
    """Pair activity identifiers with their names, skipping malformed ones."""
    options: list[ContextOption] = []
    if not isinstance(identifiers, (list, tuple)):
        return []

    for identifier in identifiers:
        if not isinstance(identifier, str) or not identifier:
            continue
        try:
            name = name_of(identifier)
        except Exception:
            name = ""
        options.append(
            ContextOption(identifier=identifier, name=name if isinstance(name, str) else "")
        )
    return options


class DBusContextProvider:
    """Reads activities and virtual desktops from the live session bus.

    Every query is read-only and degrades to an empty list when the service is
    unavailable, so the GUI still opens without a running KDE session.
    """

    def __init__(self, bus=_DEFAULT_BUS):
        # An explicit bus=None means "no bus available", which is distinct from
        # omitting the argument to get the session bus.
        if bus is _DEFAULT_BUS:
            bus = QDBusConnection.sessionBus()
        self._bus = bus

    def _usable_bus(self):
        if self._bus is None:
            return None
        try:
            if not self._bus.isConnected():
                return None
        except Exception:
            return None
        return self._bus

    def activities(self) -> list[ContextOption]:
        bus = self._usable_bus()
        if bus is None:
            return []
        try:
            interface = QDBusInterface(
                ACTIVITY_SERVICE, ACTIVITY_PATH, ACTIVITY_INTERFACE, bus)
            interface.setTimeout(DBUS_TIMEOUT_MS)
            if not interface.isValid():
                return []

            reply = QDBusReply(interface.call("ListActivities"))
            if not reply.isValid():
                return []

            def name_of(identifier: str) -> str:
                name_reply = QDBusReply(interface.call("ActivityName", identifier))
                return name_reply.value() if name_reply.isValid() else ""

            return decode_activities(reply.value(), name_of)
        except Exception:
            return []

    def desktops(self) -> list[ContextOption]:
        bus = self._usable_bus()
        if bus is None:
            return []
        try:
            interface = QDBusInterface(
                KWIN_SERVICE, VIRTUAL_DESKTOP_PATH, PROPERTIES_INTERFACE, bus)
            interface.setTimeout(DBUS_TIMEOUT_MS)
            if not interface.isValid():
                return []

            reply = QDBusReply(
                interface.call("Get", VIRTUAL_DESKTOP_INTERFACE, "desktops"))
            if not reply.isValid():
                return []
            return decode_desktops(reply.value())
        except Exception:
            return []
