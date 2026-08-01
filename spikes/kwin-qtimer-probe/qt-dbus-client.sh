#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later

if command -v qdbus6 >/dev/null 2>&1; then
    QDBUS="$(command -v qdbus6)"
elif command -v qdbus-qt6 >/dev/null 2>&1; then
    QDBUS="$(command -v qdbus-qt6)"
else
    printf 'No Qt 6 D-Bus client found (tried qdbus6 and qdbus-qt6).\n' >&2
    return 1
fi
