#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

PACKAGE_ID="hotcorners-per-monitor-qtimer-probe"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/qt-dbus-client.sh"
SCRIPT="${ROOT}/contents/code/main.js"
CURSOR_FILE="${XDG_RUNTIME_DIR:-/tmp}/${PACKAGE_ID}.cursor"

command -v journalctl >/dev/null

"${QDBUS}" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript \
    "${PACKAGE_ID}" >/dev/null 2>&1 || true

journalctl --user -n 0 --show-cursor --no-pager \
    | sed -n 's/^-- cursor: //p' >"${CURSOR_FILE}"
test -s "${CURSOR_FILE}"

script_id="$("${QDBUS}" org.kde.KWin /Scripting \
    org.kde.kwin.Scripting.loadScript "${SCRIPT}" "${PACKAGE_ID}")"
cleanup_on_error() {
    "${QDBUS}" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript \
        "${PACKAGE_ID}" >/dev/null 2>&1 || true
    rm -f "${CURSOR_FILE}"
}
trap cleanup_on_error ERR

case "${script_id}" in
    ''|*[!0-9]*)
        printf 'loadScript returned invalid id: %s\n' "${script_id}" >&2
        cleanup_on_error
        exit 1
        ;;
esac

"${QDBUS}" org.kde.KWin "/Scripting/Script${script_id}" \
    org.kde.kwin.Script.run
trap - ERR

printf 'Loaded %s as /Scripting/Script%s\n' "${PACKAGE_ID}" "${script_id}"
printf 'Journal cursor: %s\n' "${CURSOR_FILE}"
