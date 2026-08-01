#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

PACKAGE_ID="hotcorners-per-monitor-qtimer-probe"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/qt-dbus-client.sh"
CURSOR_FILE="${XDG_RUNTIME_DIR:-/tmp}/${PACKAGE_ID}.cursor"
OUTPUT_DIR="${1:-}"

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(mktemp -d /tmp/hcpm-qtimer-probe.XXXXXX)"
else
    mkdir -p "${OUTPUT_DIR}"
fi

cleanup() {
    "${ROOT}/uninstall-probe.sh" >/dev/null 2>&1 || true
}
trap cleanup EXIT

{
    printf 'XDG_SESSION_TYPE=%s\n' "${XDG_SESSION_TYPE-}"
    printf 'XDG_CURRENT_DESKTOP=%s\n' "${XDG_CURRENT_DESKTOP-}"
    plasmashell --version 2>/dev/null || true
    kwin_wayland --version 2>/dev/null || true
    kwin_x11 --version 2>/dev/null || true
    qtpaths6 --qt-version 2>/dev/null || true
} >"${OUTPUT_DIR}/environment.txt"

"${ROOT}/install-probe.sh"
cursor="$(cat "${CURSOR_FILE}")"

ready=false
for _ in $(seq 1 80); do
    if journalctl --user --after-cursor "${cursor}" -o cat --no-pager \
        | grep -Fq 'HCPM_QTIMER_PROBE {"test":"suite","event":"ready-for-unload"'; then
        ready=true
        break
    fi
    sleep 0.25
done

if [[ "${ready}" != "true" ]]; then
    printf 'Probe did not reach ready-for-unload\n' >&2
    exit 1
fi

unload_output="$("${ROOT}/uninstall-probe.sh")"
printf '%s\n' "${unload_output}"
if [[ "${unload_output}" != unloaded=true* ]]; then
    printf 'Probe was not loaded during cleanup\n' >&2
    exit 1
fi
trap - EXIT

sleep 6
journalctl --user --after-cursor "${cursor}" -o short-monotonic --no-pager \
    >"${OUTPUT_DIR}/journal.log"

python3 "${ROOT}/verify-log.py" \
    --cleanup-confirmed "${OUTPUT_DIR}/journal.log" \
    | tee "${OUTPUT_DIR}/verification.json"

loaded="$("${QDBUS}" org.kde.KWin /Scripting \
    org.kde.kwin.Scripting.isScriptLoaded "${PACKAGE_ID}")"
printf 'isScriptLoaded=%s\n' "${loaded}"
printf 'Artifacts: %s\n' "${OUTPUT_DIR}"
test "${loaded}" = "false"
