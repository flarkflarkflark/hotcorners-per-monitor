#!/usr/bin/env bash
# Hot Corners Per Monitor — interactive setup
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One command, everything works. Installs files, enables the KWin script,
# optionally disables the conflicting built-in hot corners, and launches
# the configuration GUI.
#
# Usage:
#   ./setup.sh                  Interactive setup (recommended)
#   ./setup.sh --yes            Non-interactive, accept all defaults
#   ./setup.sh --no-launch      Don't launch GUI at the end
#   ./setup.sh --keep-defaults  Don't disable KDE's built-in hot corners
#   ./setup.sh --help           Show this message

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SCRIPT_ID="hotcorners-per-monitor"

# Target locations (user-level install — no sudo needed)
KWIN_DIR="${HOME}/.local/share/kwin/scripts/${SCRIPT_ID}"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
LOCALE_DIR="${HOME}/.local/share/locale"
LIB_DIR="${HOME}/.local/share/${SCRIPT_ID}"
HELPER_LIB_DIR="${HOME}/.local/lib/${SCRIPT_ID}/command-runner"
HELPER_PY="${HELPER_LIB_DIR}/command_runner.py"
DBUS_SERVICE_DIR="${HOME}/.local/share/dbus-1/services"
HELPER_SERVICE="${DBUS_SERVICE_DIR}/org.flark.HotCorners.CommandRunner.service"
PYTHON_BIN="$(command -v python3 || true)"

# Flags
NONINTERACTIVE=0
LAUNCH_GUI=1
DISABLE_DEFAULTS=ask  # ask, yes, no

# Pretty output
if [ -t 1 ]; then
    C_RESET='\033[0m'
    C_BOLD='\033[1m'
    C_DIM='\033[2m'
    C_RED='\033[31m'
    C_GREEN='\033[32m'
    C_YELLOW='\033[33m'
    C_BLUE='\033[34m'
    C_CYAN='\033[36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''
    C_YELLOW=''; C_BLUE=''; C_CYAN=''
fi

say()    { printf '%b%s%b\n'   "${C_BOLD}${C_BLUE}" "==> $*"   "${C_RESET}"; }
step()   { printf '%b%s%b\n'   "${C_CYAN}"          " -> $*"   "${C_RESET}"; }
ok()     { printf '%b%s%b\n'   "${C_GREEN}"         " ✓ $*"    "${C_RESET}"; }
warn()   { printf '%b%s%b\n'   "${C_YELLOW}"        " ! $*"    "${C_RESET}"; }
fail()   { printf '%b%s%b\n'   "${C_RED}${C_BOLD}"  " ✗ $*"    "${C_RESET}" >&2; }
dim()    { printf '%b%s%b\n'   "${C_DIM}"           "    $*"   "${C_RESET}"; }

# ----- argument parsing -----
for arg in "$@"; do
    case "$arg" in
        -y|--yes)            NONINTERACTIVE=1 ;;
        --no-launch)         LAUNCH_GUI=0 ;;
        --keep-defaults)     DISABLE_DEFAULTS=no ;;
        --disable-defaults)  DISABLE_DEFAULTS=yes ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -n 15
            exit 0
            ;;
        *) fail "Unknown option: $arg"; exit 1 ;;
    esac
done

confirm() {
    # confirm "question" default(y|n) — returns 0 for yes, 1 for no
    local question="$1"
    local default="${2:-y}"
    if [ "$NONINTERACTIVE" = "1" ]; then
        [ "$default" = "y" ]
        return $?
    fi
    local prompt
    if [ "$default" = "y" ]; then prompt="[Y/n]"; else prompt="[y/N]"; fi
    while true; do
        printf '%b%s%b %s ' "${C_BOLD}" "${question}" "${C_RESET}" "$prompt"
        local reply
        read -r reply || reply=""
        reply="${reply,,}"
        case "$reply" in
            ""|y|yes|j|ja) [ "$default" = "y" ] || [ "$reply" != "" ]; return $? ;;
            n|no|nee)  return 1 ;;
            *) warn "Please answer y or n." ;;
        esac
    done
}

# ----- dependency check -----
say "Checking dependencies"

MISSING=()

for cmd in kwriteconfig6 kreadconfig6 kpackagetool6 python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "found: $cmd"
    else
        fail "missing: $cmd"
        MISSING+=("$cmd")
    fi
done

# qdbus6 OR qdbus-qt6 OR qdbus (some distros ship only one)
if command -v qdbus6 >/dev/null 2>&1; then
    QDBUS=qdbus6
    ok "found: qdbus6"
elif command -v qdbus-qt6 >/dev/null 2>&1; then
    QDBUS=qdbus-qt6
    ok "found: qdbus-qt6 (using as qdbus6 fallback)"
elif command -v qdbus >/dev/null 2>&1; then
    QDBUS=qdbus
    ok "found: qdbus (using as qdbus6 fallback)"
else
    fail "missing: qdbus6 (or qdbus-qt6/qdbus)"
    MISSING+=("qdbus6")
fi

# PyQt6 check
if python3 -c "import PyQt6.QtWidgets" 2>/dev/null; then
    ok "found: python3-pyqt6"
else
    fail "missing: PyQt6 (Python module)"
    MISSING+=("python3-pyqt6")
fi

if python3 -c "import PyQt6.QtDBus" 2>/dev/null; then
    ok "found: python3-pyqt6-qtdbus"
else
    fail "missing: PyQt6.QtDBus (Python module)"
    MISSING+=("python3-pyqt6-qtdbus")
fi

# msgfmt — soft dependency, we ship pre-built .mo files anyway
if command -v msgfmt >/dev/null 2>&1; then
    ok "found: msgfmt (optional)"
    HAVE_MSGFMT=1
else
    warn "msgfmt not found — will use pre-built .mo files"
    HAVE_MSGFMT=0
fi

if [ "${#MISSING[@]}" -ne 0 ]; then
    echo
    fail "Cannot continue — install missing packages first."
    echo
    # Distro hints
    if [ -r /etc/os-release ]; then
        . /etc/os-release
        case "${ID:-unknown}" in
            arch|manjaro|endeavouros|cachyos|garuda)
                say "On Arch:"
                step "sudo pacman -S --needed plasma-workspace python-pyqt6 qt6-tools"
                ;;
            ubuntu|debian|linuxmint|pop|kubuntu|neon)
                say "On Debian/Ubuntu:"
                step "sudo apt install plasma-workspace python3-pyqt6 qt6-tools-dev-tools"
                ;;
            fedora|nobara)
                say "On Fedora:"
                step "sudo dnf install plasma-workspace python3-pyqt6 qt6-qttools"
                ;;
            opensuse*|suse)
                say "On openSUSE:"
                step "sudo zypper install plasma6-workspace python3-qt6 qt6-tools"
                ;;
            *)
                say "Install the equivalents of these packages for ${ID}:"
                step "  plasma-workspace, python3-pyqt6, qt6-tools"
                ;;
        esac
    fi
    exit 1
fi

# ----- install KWin script -----
echo
say "Installing KWin script"

mkdir -p "${KWIN_DIR}"
cp -r "${SCRIPT_DIR}/kwin-script/"* "${KWIN_DIR}/"
ok "Installed to ${KWIN_DIR}"

# Also register with kpackagetool6 so System Settings sees it.
# Use upgrade if already installed, install otherwise. Errors are non-fatal —
# the script also works from ~/.local/share/kwin/scripts/ even without registration.
if kpackagetool6 --type=KWin/Script --list 2>/dev/null | grep -qx "${SCRIPT_ID}"; then
    step "Upgrading existing kpackagetool6 registration"
    kpackagetool6 --type=KWin/Script --upgrade "${KWIN_DIR}" >/dev/null 2>&1 \
        || warn "kpackagetool6 upgrade returned non-zero (continuing)"
else
    step "Registering with kpackagetool6"
    kpackagetool6 --type=KWin/Script --install "${KWIN_DIR}" >/dev/null 2>&1 \
        || warn "kpackagetool6 install returned non-zero (continuing)"
fi
ok "KWin script registered"

# ----- install GUI -----
echo
say "Installing configuration GUI"

mkdir -p "${LIB_DIR}"
cp "${SCRIPT_DIR}/config-gui/hotcorners_config.py" "${LIB_DIR}/"
cp "${SCRIPT_DIR}/config-gui/config_schema.py" "${LIB_DIR}/"
ok "GUI installed to ${LIB_DIR}"

mkdir -p "${BIN_DIR}"
cat > "${BIN_DIR}/hotcorners-config" << EOF
#!/usr/bin/env bash
exec python3 "${LIB_DIR}/hotcorners_config.py" "\$@"
EOF
chmod +x "${BIN_DIR}/hotcorners-config"
ok "Launcher installed to ${BIN_DIR}/hotcorners-config"

# PATH check
if ! echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
    warn "${BIN_DIR} is not in your PATH"
    dim "Add to your shell profile: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

mkdir -p "${DESKTOP_DIR}"
cp "${SCRIPT_DIR}/config-gui/hotcorners-config.desktop" "${DESKTOP_DIR}/"
ok "Desktop entry installed"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
fi

# ----- install command helper -----
echo
say "Installing command runner helper"

mkdir -p "${HELPER_LIB_DIR}" "${DBUS_SERVICE_DIR}"
if [ ! -w "${HELPER_LIB_DIR}" ] || [ ! -w "${DBUS_SERVICE_DIR}" ]; then
    fail "Cannot write command runner install directories under ~/.local"
    exit 1
fi

helper_tmp="$(mktemp "${HELPER_PY}.tmp.XXXXXX")"
cp "${SCRIPT_DIR}/command-runner/command_runner.py" "${helper_tmp}"
chmod 0755 "${helper_tmp}"
mv "${helper_tmp}" "${HELPER_PY}"
ok "Command runner installed to ${HELPER_PY}"

service_tmp="$(mktemp "${HELPER_SERVICE}.tmp.XXXXXX")"
python_exec_escaped="$(printf '%s' "${PYTHON_BIN}" | sed -e 's/\\/\\\\/g' -e 's/ /\\ /g')"
helper_exec_escaped="$(printf '%s' "${HELPER_PY}" | sed -e 's/\\/\\\\/g' -e 's/ /\\ /g')"
cat > "${service_tmp}" << EOF
[D-BUS Service]
Name=org.flark.HotCorners.CommandRunner
Exec=${python_exec_escaped} ${helper_exec_escaped}
EOF
chmod 0644 "${service_tmp}"
mv "${service_tmp}" "${HELPER_SERVICE}"
ok "D-Bus activation file installed to ${HELPER_SERVICE}"

if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    step "Probing command helper activation on current session bus"
    activation_output="$("${QDBUS}" org.flark.HotCorners.CommandRunner \
        /CommandRunner org.flark.HotCorners.CommandRunner1.Run \
        /usr/bin/true '[]' 2>/dev/null || true)"
    if printf '%s\n' "${activation_output}" | head -n1 | grep -qx 'true'; then
        ok "Command helper activation probe passed"
    else
        warn "Command helper activation probe failed in current session"
        if [ "${HCPM_REQUIRE_HELPER_ACTIVATION:-0}" = "1" ]; then
            fail "Activation probe is required and failed"
            exit 1
        fi
    fi
else
    warn "No session bus detected; skipped command helper activation probe"
fi

# ----- install translations -----
echo
say "Installing translations"

mkdir -p "${LOCALE_DIR}"
for po in "${SCRIPT_DIR}"/config-gui/translations/*/LC_MESSAGES/hotcorners-config.po; do
    [ -e "$po" ] || continue
    lang_dir="$(dirname "$(dirname "${po}")")"
    lang="$(basename "${lang_dir}")"
    target_dir="${LOCALE_DIR}/${lang}/LC_MESSAGES"
    mkdir -p "${target_dir}"
    src_mo="$(dirname "${po}")/hotcorners-config.mo"
    if [ "$HAVE_MSGFMT" = "1" ]; then
        msgfmt "${po}" -o "${target_dir}/hotcorners-config.mo" 2>/dev/null
        ok "${lang}: compiled and installed"
    elif [ -f "${src_mo}" ]; then
        cp "${src_mo}" "${target_dir}/"
        ok "${lang}: pre-built .mo installed"
    else
        warn "${lang}: skipped (no msgfmt and no pre-built .mo)"
    fi
done

# ----- enable script in kwinrc -----
echo
say "Enabling the KWin script"

# Plasma uses '<scriptid>Enabled' as the key.
ENABLE_KEY="${SCRIPT_ID}Enabled"
current="$(kreadconfig6 --file kwinrc --group Plugins --key "${ENABLE_KEY}" 2>/dev/null || echo)"
if [ "${current}" = "true" ]; then
    ok "Script was already enabled"
else
    kwriteconfig6 --file kwinrc --group Plugins --key "${ENABLE_KEY}" true
    ok "Script enabled in kwinrc"
fi

# ----- offer to disable conflicting built-in hot corners -----
echo
say "Checking built-in KDE hot corners"

BUILTIN_BORDERS=(TopLeft Top TopRight Right BottomRight Bottom BottomLeft Left)
ACTIVE_BUILTINS=()
for border in "${BUILTIN_BORDERS[@]}"; do
    val="$(kreadconfig6 --file kwinrc --group ElectricBorders --key "${border}" 2>/dev/null || echo)"
    if [ -n "${val}" ] && [ "${val}" != "None" ] && [ "${val}" != "none" ]; then
        ACTIVE_BUILTINS+=("${border}=${val}")
    fi
done

DISABLE=0
if [ "${#ACTIVE_BUILTINS[@]}" -gt 0 ]; then
    warn "${#ACTIVE_BUILTINS[@]} built-in hot corner(s) active:"
    for entry in "${ACTIVE_BUILTINS[@]}"; do
        dim "    ${entry}"
    done
    echo
    case "$DISABLE_DEFAULTS" in
        yes) DISABLE=1 ;;
        no)  DISABLE=0; warn "Keeping built-in hot corners enabled per --keep-defaults" ;;
        ask)
            dim "These will trigger in addition to your per-monitor config,"
            dim "causing the inner-monitor corners to fire actions you didn't set up."
            if confirm "Disable the built-in hot corners now?" y; then
                DISABLE=1
            else
                DISABLE=0
            fi
            ;;
    esac
    if [ "$DISABLE" = "1" ]; then
        # Back up the current values first, so uninstall can restore
        mkdir -p "${HOME}/.config"
        BACKUP_FILE="${HOME}/.config/${SCRIPT_ID}-backup-electric-borders.conf"
        {
            echo "# Backup of [ElectricBorders] from kwinrc, created by"
            echo "# ${SCRIPT_ID} setup on $(date -Iseconds)"
            echo "# Restore manually with kwriteconfig6 if needed."
            echo "[ElectricBorders]"
            for entry in "${ACTIVE_BUILTINS[@]}"; do
                echo "${entry}"
            done
        } > "${BACKUP_FILE}"
        dim "Saved backup: ${BACKUP_FILE}"
        for border in "${BUILTIN_BORDERS[@]}"; do
            kwriteconfig6 --file kwinrc --group ElectricBorders --key "${border}" None
        done
        ok "Built-in hot corners disabled"
    fi
else
    ok "No conflicting built-in hot corners active"
fi

# ----- reconfigure kwin -----
echo
say "Reloading KWin"
if "${QDBUS}" org.kde.KWin /KWin reconfigure >/dev/null 2>&1; then
    ok "KWin reconfigured — script is now live"
else
    warn "Could not reload KWin via D-Bus"
    dim "You may need to log out and back in for changes to take effect."
fi

# ----- done -----
echo
printf '%b%s%b\n' "${C_GREEN}${C_BOLD}" "════════════════════════════════════════" "${C_RESET}"
printf '%b%s%b\n' "${C_GREEN}${C_BOLD}" "  Setup complete!" "${C_RESET}"
printf '%b%s%b\n' "${C_GREEN}${C_BOLD}" "════════════════════════════════════════" "${C_RESET}"
echo
dim "To configure your hot corners, run: hotcorners-config"
dim "Or find 'Hot Corners Per Monitor' in your application menu."
dim "To uninstall later: ${SCRIPT_DIR}/uninstall.sh"
echo

# ----- launch GUI -----
if [ "$LAUNCH_GUI" = "1" ]; then
    if [ "$NONINTERACTIVE" = "1" ]; then
        LAUNCH=1
    else
        if confirm "Launch the configuration GUI now?" y; then
            LAUNCH=1
        else
            LAUNCH=0
        fi
    fi
    if [ "${LAUNCH:-0}" = "1" ]; then
        say "Launching configuration GUI"
        # Detach so the setup script can exit cleanly
        ( setsid "${BIN_DIR}/hotcorners-config" >/dev/null 2>&1 & ) || true
        ok "Opened in a new window"
    fi
fi
