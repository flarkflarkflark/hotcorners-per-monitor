#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QObject, QCoreApplication, QTimer, pyqtClassInfo, pyqtSlot
from PyQt6.QtDBus import QDBusConnection

BUS_NAME = "org.flark.HotCorners.CommandRunner"
OBJECT_PATH = "/CommandRunner"
INTERFACE_NAME = "org.flark.HotCorners.CommandRunner1"
METHOD_NAME = "Run"

MAX_PROGRAM_BYTES = 4096
MAX_ARGUMENTS = 128
MAX_ARGUMENT_BYTES = 16 * 1024
MAX_TOTAL_ARGUMENT_BYTES = 128 * 1024
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def utf8_byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def validate_program(program: object) -> tuple[bool, str]:
    if not isinstance(program, str) or not program:
        return False, "invalid-program"
    if "\x00" in program:
        return False, "invalid-program"
    if utf8_byte_length(program) > MAX_PROGRAM_BYTES:
        return False, "invalid-program"
    if "/" in program and not os.path.isabs(program):
        return False, "invalid-program"
    return True, ""


def parse_arguments(arguments_json: object) -> tuple[bool, list[str] | None, str]:
    if not isinstance(arguments_json, str):
        return False, None, "invalid-arguments-json"
    try:
        parsed = json.loads(arguments_json)
    except json.JSONDecodeError:
        return False, None, "invalid-arguments-json"

    if not isinstance(parsed, list):
        return False, None, "invalid-arguments-json"
    if len(parsed) > MAX_ARGUMENTS:
        return False, None, "too-many-arguments"

    total = 0
    arguments: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            return False, None, "invalid-arguments-json"
        if "\x00" in item:
            return False, None, "invalid-arguments-json"
        item_bytes = utf8_byte_length(item)
        if item_bytes > MAX_ARGUMENT_BYTES:
            return False, None, "argument-too-large"
        total += item_bytes
        if total > MAX_TOTAL_ARGUMENT_BYTES:
            return False, None, "arguments-too-large"
        arguments.append(item)

    return True, arguments, ""


def resolve_program(
    program: str,
    *,
    path_env: str,
    which_func: Callable[[str, str | None], str | None] = shutil.which,
) -> tuple[bool, str | None, str]:
    if os.path.isabs(program):
        candidate = program
    else:
        candidate = which_func(program, path=path_env)
        if candidate is None:
            return False, None, "program-not-found"

    if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
        return False, None, "program-not-executable"

    return True, candidate, ""


def spawn_command(
    executable: str,
    arguments: list[str],
    *,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> tuple[bool, str, subprocess.Popen | None]:
    try:
        process = popen_factory(
            [executable, *arguments],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return False, "spawn-failed", None

    return True, "", process


@dataclass
class CommandRunnerCore:
    path_env: str | None = None
    which_func: Callable[[str, str | None], str | None] = shutil.which
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen

    def run_command(self, program: object, arguments_json: object) -> tuple[bool, str, subprocess.Popen | None]:
        ok, error_name = validate_program(program)
        if not ok:
            return False, error_name, None

        ok, arguments, error_name = parse_arguments(arguments_json)
        if not ok:
            return False, error_name, None

        effective_path = self.path_env if self.path_env is not None else os.environ.get("PATH", DEFAULT_PATH)
        ok, resolved, error_name = resolve_program(
            program,
            path_env=effective_path,
            which_func=self.which_func,
        )
        if not ok:
            return False, error_name, None

        return spawn_command(
            resolved,
            arguments,
            popen_factory=self.popen_factory,
        )


@pyqtClassInfo("D-Bus Interface", INTERFACE_NAME)
class CommandRunnerObject(QObject):
    def __init__(self, core: CommandRunnerCore) -> None:
        super().__init__()
        self._core = core
        self._children: list[subprocess.Popen] = []

        self._reaper = QTimer(self)
        self._reaper.setInterval(5000)
        self._reaper.timeout.connect(self._reap_children)
        if QCoreApplication.instance() is not None:
            self._reaper.start()

    def _reap_children(self) -> None:
        alive: list[subprocess.Popen] = []
        for process in self._children:
            if process.poll() is None:
                alive.append(process)
        self._children = alive

    @pyqtSlot(str, str, result="QVariantList")
    def Run(self, program: str, arguments_json: str) -> list[object]:
        try:
            accepted, error_name, process = self._core.run_command(program, arguments_json)
        except Exception:
            return [False, "internal-error"]

        if accepted and process is not None:
            self._children.append(process)

        return [bool(accepted), str(error_name)]


def main() -> int:
    app = QCoreApplication(sys.argv)
    core = CommandRunnerCore()
    service = CommandRunnerObject(core)

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        print("command-runner: session bus not available", file=sys.stderr)
        return 1

    if not bus.registerService(BUS_NAME):
        print("command-runner: service already running or unavailable", file=sys.stderr)
        return 1

    if not bus.registerObject(
        OBJECT_PATH,
        service,
        QDBusConnection.RegisterOption.ExportAllSlots,
    ):
        print("command-runner: failed to register object", file=sys.stderr)
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
