#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

PACKAGE_ID="hotcorners-per-monitor-qtimer-probe"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/qt-dbus-client.sh"
CURSOR_FILE="${XDG_RUNTIME_DIR:-/tmp}/${PACKAGE_ID}.cursor"

unloaded="$("${QDBUS}" org.kde.KWin /Scripting \
    org.kde.kwin.Scripting.unloadScript "${PACKAGE_ID}")"
if [[ "${unloaded}" != "true" && "${unloaded}" != "false" ]]; then
    printf 'Unexpected unloadScript result: %s\n' "${unloaded}" >&2
    exit 1
fi

rm -f "${CURSOR_FILE}"
printf 'unloaded=%s package=%s\n' "${unloaded}" "${PACKAGE_ID}"
