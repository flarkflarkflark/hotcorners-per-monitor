#!/usr/bin/env bash
# Hot Corners Per Monitor — uninstaller
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Removes all files installed by setup.sh and disables the KWin script.
# Does NOT touch the [ElectricBorders] group — if you let setup.sh disable
# the built-in hot corners, restore them yourself from the backup file at
# ~/.config/hotcorners-per-monitor-backup-electric-borders.conf
#
# Usage:
#   ./uninstall.sh         Interactive
#   ./uninstall.sh --yes   Non-interactive

set -euo pipefail

SCRIPT_ID="hotcorners-per-monitor"
KWIN_DIR="${HOME}/.local/share/kwin/scripts/${SCRIPT_ID}"
BIN_FILE="${HOME}/.local/bin/hotcorners-config"
DESKTOP_FILE="${HOME}/.local/share/applications/hotcorners-config.desktop"
LIB_DIR="${HOME}/.local/share/${SCRIPT_ID}"
HELPER_LIB_DIR="${HOME}/.local/lib/${SCRIPT_ID}/command-runner"
HELPER_PY="${HELPER_LIB_DIR}/command_runner.py"
DBUS_SERVICE_FILE="${HOME}/.local/share/dbus-1/services/org.flark.HotCorners.CommandRunner.service"
BACKUP_FILE="${HOME}/.config/${SCRIPT_ID}-backup-electric-borders.conf"

NONINTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) NONINTERACTIVE=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -n 12
            exit 0
            ;;
    esac
done

if [ -t 1 ]; then
    C_RESET='\033[0m'; C_BOLD='\033[1m'; C_DIM='\033[2m'
    C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_BLUE='\033[34m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''
fi

say()  { printf '%b%s%b\n' "${C_BOLD}${C_BLUE}" "==> $*" "${C_RESET}"; }
ok()   { printf '%b%s%b\n' "${C_GREEN}" " ✓ $*" "${C_RESET}"; }
warn() { printf '%b%s%b\n' "${C_YELLOW}" " ! $*" "${C_RESET}"; }
dim()  { printf '%b%s%b\n' "${C_DIM}" "    $*" "${C_RESET}"; }

confirm() {
    [ "$NONINTERACTIVE" = "1" ] && return 0
    printf '%b%s%b [Y/n] ' "${C_BOLD}" "$1" "${C_RESET}"
    local reply; read -r reply || reply=""
    reply="${reply,,}"
    [ -z "$reply" ] || [ "$reply" = "y" ] || [ "$reply" = "yes" ] || [ "$reply" = "j" ]
}

if ! confirm "Remove Hot Corners Per Monitor from your system?"; then
    echo "Cancelled."
    exit 0
fi

say "Disabling KWin script"
ENABLE_KEY="${SCRIPT_ID}Enabled"
if command -v kwriteconfig6 >/dev/null 2>&1; then
    kwriteconfig6 --file kwinrc --group Plugins --key "${ENABLE_KEY}" false
    ok "Set ${ENABLE_KEY}=false in kwinrc"
fi

# Also clear the script's own config section (the JSON blob)
if command -v kwriteconfig6 >/dev/null 2>&1; then
    kwriteconfig6 --file kwinrc --group "Script-${SCRIPT_ID}" \
        --key MonitorConfigs --delete 2>/dev/null || true
fi

# Unload the running script from KWin's memory before removing its files, so
# the process backing it stops immediately rather than lingering until next
# login. A plain "qdbus6 org.kde.KWin /KWin reconfigure" was proven live
# (Plasma/KWin 6.7.3 Wayland) not to unload a script's code, unlike
# unloadScript. This is best-effort: an actual D-Bus error is reported but
# never blocks the file cleanup below, and a script that was already
# unloaded (or never loaded) is not treated as an error.
say "Unloading the KWin script"
UNLOAD_QDBUS=""
if command -v qdbus6 >/dev/null 2>&1; then
    UNLOAD_QDBUS=qdbus6
elif command -v qdbus-qt6 >/dev/null 2>&1; then
    UNLOAD_QDBUS=qdbus-qt6
elif command -v qdbus >/dev/null 2>&1; then
    UNLOAD_QDBUS=qdbus
fi

if [ -n "${UNLOAD_QDBUS}" ]; then
    if UNLOAD_OUTPUT="$("${UNLOAD_QDBUS}" org.kde.KWin /Scripting unloadScript "${SCRIPT_ID}" 2>&1)"; then
        UNLOAD_STATUS=0
    else
        UNLOAD_STATUS=$?
    fi

    if [ "${UNLOAD_STATUS}" -ne 0 ]; then
        warn "Could not unload the running KWin script (D-Bus error): ${UNLOAD_OUTPUT}"
        dim "Continuing with file removal anyway."
    elif [ "${UNLOAD_OUTPUT}" = "true" ]; then
        ok "KWin script unloaded"
    else
        dim "KWin script was not currently loaded"
    fi
else
    dim "qdbus6 not found; skipping KWin script unload (D-Bus unavailable)"
fi

say "Removing files"
if [ -d "${KWIN_DIR}" ]; then
    rm -rf "${KWIN_DIR}"
    ok "Removed ${KWIN_DIR}"
fi

# Try kpackagetool6 too
if command -v kpackagetool6 >/dev/null 2>&1; then
    kpackagetool6 --type=KWin/Script --remove "${SCRIPT_ID}" >/dev/null 2>&1 || true
fi

for path in "${BIN_FILE}" "${DESKTOP_FILE}" "${HELPER_PY}" "${DBUS_SERVICE_FILE}"; do
    if [ -e "${path}" ]; then
        rm -f "${path}"
        ok "Removed ${path}"
    fi
done

if [ -d "${LIB_DIR}" ]; then
    rm -rf "${LIB_DIR}"
    ok "Removed ${LIB_DIR}"
fi

if [ -d "${HELPER_LIB_DIR}" ]; then
    rmdir "${HELPER_LIB_DIR}" 2>/dev/null || true
fi
if [ -d "${HOME}/.local/lib/${SCRIPT_ID}" ]; then
    rmdir "${HOME}/.local/lib/${SCRIPT_ID}" 2>/dev/null || true
fi

# Translations — remove every installed hotcorners-config catalog,
# whatever language it's in, rather than a hardcoded language list.
for mo in "${HOME}/.local/share/locale/"*/LC_MESSAGES/hotcorners-config.mo; do
    [ -f "$mo" ] || continue
    rm -f "$mo" && ok "Removed ${mo}"
done

echo
if [ -f "${BACKUP_FILE}" ]; then
    warn "Built-in hot corners backup found at:"
    dim "    ${BACKUP_FILE}"
    dim "Setup.sh disabled the standard KDE hot corners. To restore them,"
    dim "either re-enable them in System Settings → Screen Edges, or apply"
    dim "the values from that backup file with kwriteconfig6."
fi

echo
warn "If command helper was already active, it may live until session end."
ok "Uninstall complete."
