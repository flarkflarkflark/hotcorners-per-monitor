#!/usr/bin/env bash
# Build a deterministic KDE Store distribution package for the
# hotcorners-per-monitor KWin/Script.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The KDE Store / "Get New Scripts" mechanism installs exactly one
# KPackage (kwin-script/) via kpackagetool6 -- it never runs a shell
# script. This tool packages ONLY that KWin/Script payload as a zip with
# the correct top-level folder layout, validates it, and self-tests a
# full install/upgrade/remove lifecycle with the real kpackagetool6 in an
# isolated HOME before declaring the artifact ready.
#
# Usage:
#   tools/build-kde-store-package.sh [--allow-dirty] [--require-tag] [--skip-verify]

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT="$( cd "${SCRIPT_DIR}/.." && pwd )"
PACKAGE_ID="hotcorners-per-monitor"
KWIN_SRC="${ROOT}/kwin-script"
METADATA="${KWIN_SRC}/metadata.json"
DIST_DIR="${ROOT}/dist"

ALLOW_DIRTY=0
REQUIRE_TAG=0
SKIP_VERIFY=0

for arg in "$@"; do
    case "$arg" in
        --allow-dirty)  ALLOW_DIRTY=1 ;;
        --require-tag)  REQUIRE_TAG=1 ;;
        --skip-verify)  SKIP_VERIFY=1 ;;
        -h|--help)
            sed -n '2,17p' "$0"
            exit 0
            ;;
        *)
            printf 'unknown argument: %s\n' "$arg" >&2
            exit 2
            ;;
    esac
done

if [ -t 1 ]; then
    C_RESET='\033[0m'; C_BOLD='\033[1m'; C_DIM='\033[2m'
    C_RED='\033[31m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_CYAN='\033[36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''
fi
say()  { printf '%b%s%b\n' "${C_BOLD}${C_CYAN}" "==> $*" "${C_RESET}"; }
ok()   { printf '%b%s%b\n' "${C_GREEN}"         " ✓ $*"  "${C_RESET}"; }
warn() { printf '%b%s%b\n' "${C_YELLOW}"        " ! $*"  "${C_RESET}"; }
fail() { printf '%b%s%b\n' "${C_RED}${C_BOLD}"  " ✗ $*"  "${C_RESET}" >&2; }
dim()  { printf '%b%s%b\n' "${C_DIM}"           "    $*" "${C_RESET}"; }

WORKDIR=""
cleanup() {
    [ -n "$WORKDIR" ] && rm -rf "$WORKDIR"
}
trap cleanup EXIT

require_tool() {
    command -v "$1" >/dev/null 2>&1 || { fail "required tool not found: $1"; exit 1; }
}

# ---------------------------------------------------------------------------
# 1. Dirty-tree guard
# ---------------------------------------------------------------------------
say "Checking working tree state"
cd "$ROOT"
require_tool git
if [ "$ALLOW_DIRTY" -eq 0 ]; then
    if [ -n "$(git status --porcelain)" ]; then
        fail "working tree is not clean; commit or stash changes first (or pass --allow-dirty)"
        git status --short
        exit 1
    fi
    ok "working tree is clean"
else
    warn "skipping dirty-tree check (--allow-dirty)"
fi
HEAD_SHA="$(git rev-parse HEAD)"
dim "HEAD: ${HEAD_SHA}"

# ---------------------------------------------------------------------------
# 2. Version detection from metadata.json
# ---------------------------------------------------------------------------
say "Reading package version"
require_tool jq
[ -f "$METADATA" ] || { fail "missing $METADATA"; exit 1; }
VERSION="$(jq -r '.KPlugin.Version' "$METADATA")"
PKG_ID_FROM_METADATA="$(jq -r '.KPlugin.Id' "$METADATA")"
[ "$PKG_ID_FROM_METADATA" = "$PACKAGE_ID" ] || {
    fail "metadata.json KPlugin.Id ('${PKG_ID_FROM_METADATA}') does not match expected '${PACKAGE_ID}'"
    exit 1
}
[ -n "$VERSION" ] && [ "$VERSION" != "null" ] || { fail "could not read KPlugin.Version from $METADATA"; exit 1; }
ok "version: ${VERSION}"

# ---------------------------------------------------------------------------
# 3. Optional tag cross-check
# ---------------------------------------------------------------------------
TAG="v${VERSION}"
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
    TAG_SHA="$(git rev-parse "${TAG}^{commit}")"
    if [ "$TAG_SHA" = "$HEAD_SHA" ]; then
        ok "HEAD matches tag ${TAG}"
    else
        warn "tag ${TAG} exists but points elsewhere (${TAG_SHA}); building from HEAD (${HEAD_SHA}) anyway"
        [ "$REQUIRE_TAG" -eq 0 ] || { fail "--require-tag: HEAD must match ${TAG}"; exit 1; }
    fi
else
    warn "no tag ${TAG} found; building an untagged/pre-release artifact"
    [ "$REQUIRE_TAG" -eq 0 ] || { fail "--require-tag: tag ${TAG} does not exist"; exit 1; }
fi

# ---------------------------------------------------------------------------
# 4. KWin-payload-only copy (tracked files only, so no __pycache__/build
#    cruft or untracked local edits can leak into the shipped artifact)
# ---------------------------------------------------------------------------
say "Staging KWin/Script payload"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/hcpm-store-build.XXXXXX")"
STAGE_ROOT="${WORKDIR}/stage"
PKG_DIR="${STAGE_ROOT}/${PACKAGE_ID}"
mkdir -p "$PKG_DIR"

mapfile -t TRACKED_FILES < <(git -C "$ROOT" ls-files -- kwin-script)
[ "${#TRACKED_FILES[@]}" -gt 0 ] || { fail "no tracked files found under kwin-script/"; exit 1; }

for rel in "${TRACKED_FILES[@]}"; do
    dest_rel="${rel#kwin-script/}"
    src="${ROOT}/${rel}"
    dest="${PKG_DIR}/${dest_rel}"
    mkdir -p "$(dirname "$dest")"
    cp -p "$src" "$dest"
done
ok "staged ${#TRACKED_FILES[@]} file(s) from kwin-script/"

# ---------------------------------------------------------------------------
# 5. Symlink rejection
# ---------------------------------------------------------------------------
if find "$PKG_DIR" -type l | grep -q .; then
    fail "staged payload contains symlinks, which is not supported in the shipped package:"
    find "$PKG_DIR" -type l
    exit 1
fi
ok "no symlinks in staged payload"

# ---------------------------------------------------------------------------
# 6. Metadata / XML / kconfig_compiler_kf6 validation
# ---------------------------------------------------------------------------
say "Validating package contents"
jq empty "${PKG_DIR}/metadata.json" && ok "metadata.json is valid JSON"

MAIN_XML="${PKG_DIR}/contents/config/main.xml"
if [ -f "$MAIN_XML" ]; then
    require_tool xmllint
    xmllint --noout "$MAIN_XML" && ok "main.xml is well-formed"

    KCONFIG_COMPILER="$(command -v kconfig_compiler_kf6 || true)"
    for candidate in /usr/lib/kf6/kconfig_compiler_kf6 /usr/libexec/kf6/kconfig_compiler_kf6 \
                      /usr/lib/x86_64-linux-gnu/libexec/kf6/kconfig_compiler_kf6; do
        [ -n "$KCONFIG_COMPILER" ] && break
        [ -x "$candidate" ] && KCONFIG_COMPILER="$candidate"
    done
    if [ -n "$KCONFIG_COMPILER" ]; then
        kcfg_check_dir="${WORKDIR}/kcfg-check"
        mkdir -p "${kcfg_check_dir}/out"
        cp "$MAIN_XML" "${kcfg_check_dir}/main.kcfg"
        cat > "${kcfg_check_dir}/main.kcfgc" <<EOF
File=main.kcfg
ClassName=HotCornersPerMonitorConfig
Singleton=true
EOF
        if ( cd "$kcfg_check_dir" && "$KCONFIG_COMPILER" -d "${kcfg_check_dir}/out" main.kcfg main.kcfgc ) >"${WORKDIR}/kcfg-check.log" 2>&1; then
            ok "main.xml compiles cleanly with kconfig_compiler_kf6"
        else
            fail "kconfig_compiler_kf6 rejected main.xml:"
            cat "${WORKDIR}/kcfg-check.log" >&2
            exit 1
        fi
    else
        warn "kconfig_compiler_kf6 not found on this system; skipping KConfigXT schema compile-check"
    fi
else
    warn "no contents/config/main.xml in payload; skipping KConfigXT validation"
fi

MAIN_JS="${PKG_DIR}/contents/code/main.js"
if [ -f "$MAIN_JS" ]; then
    if command -v node >/dev/null 2>&1; then
        node --check "$MAIN_JS" && ok "main.js has valid JavaScript syntax"
    else
        warn "node not found on this system; skipping main.js syntax check"
    fi
fi

# ---------------------------------------------------------------------------
# 7. Deterministic zip build
# ---------------------------------------------------------------------------
say "Building deterministic zip archive"
require_tool zip
require_tool sha256sum

mkdir -p "$DIST_DIR"
ARTIFACT="${DIST_DIR}/${PACKAGE_ID}-${VERSION}.zip"
rm -f "$ARTIFACT"

# Normalize mtimes to the HEAD commit time so byte-identical source trees
# always produce byte-identical archives, regardless of when/where they
# are built.
SOURCE_EPOCH="$(git -C "$ROOT" log -1 --format=%ct HEAD)"
find "$STAGE_ROOT" -exec touch -h -d "@${SOURCE_EPOCH}" {} +

# Sorted, explicit file list so archive member order never depends on
# filesystem traversal order.
( cd "$STAGE_ROOT" && find "$PACKAGE_ID" -type f | LC_ALL=C sort ) > "${WORKDIR}/filelist.txt"

( cd "$STAGE_ROOT" && zip -X -q "$ARTIFACT" -@ < "${WORKDIR}/filelist.txt" )
ok "wrote $(basename "$ARTIFACT")"

# ---------------------------------------------------------------------------
# 8. Unpack-and-diff round-trip
# ---------------------------------------------------------------------------
say "Verifying archive round-trips byte-for-byte"
require_tool unzip
UNPACK_DIR="${WORKDIR}/unpacked"
mkdir -p "$UNPACK_DIR"
unzip -q "$ARTIFACT" -d "$UNPACK_DIR"

# Every archive member must live under the top-level PACKAGE_ID/ folder --
# a flattened archive installs into the wrong place under kpackagetool6.
if find "$UNPACK_DIR" -mindepth 1 -maxdepth 1 ! -name "$PACKAGE_ID" | grep -q .; then
    fail "archive contains entries outside a single top-level ${PACKAGE_ID}/ folder"
    exit 1
fi
ok "archive has the correct top-level ${PACKAGE_ID}/ folder"

if ! diff -r "$PKG_DIR" "${UNPACK_DIR}/${PACKAGE_ID}" >"${WORKDIR}/diff.log" 2>&1; then
    fail "unpacked archive differs from staged payload:"
    cat "${WORKDIR}/diff.log" >&2
    exit 1
fi
ok "unpacked archive is byte-identical to the staged payload"

# ---------------------------------------------------------------------------
# 9/10. Isolated-HOME kpackagetool6 lifecycle self-test
# ---------------------------------------------------------------------------
if [ "$SKIP_VERIFY" -eq 1 ]; then
    warn "skipping kpackagetool6 lifecycle self-test (--skip-verify)"
elif ! command -v kpackagetool6 >/dev/null 2>&1; then
    warn "kpackagetool6 not found on this system; skipping install/upgrade/remove self-test"
else
    say "Running install/list/upgrade/remove self-test in an isolated HOME"
    TEST_HOME="${WORKDIR}/verify-home"
    mkdir -p "$TEST_HOME"
    SCRIPTS_DIR="${TEST_HOME}/.local/share/kwin/scripts/${PACKAGE_ID}"

    run_kpkg() {
        env -i HOME="$TEST_HOME" XDG_DATA_HOME="${TEST_HOME}/.local/share" \
            PATH="$PATH" kpackagetool6 --type=KWin/Script "$@"
    }

    before_snapshot="${WORKDIR}/home-before.txt"
    find "$TEST_HOME" -type f | LC_ALL=C sort > "$before_snapshot"

    run_kpkg --install "$UNPACK_DIR/${PACKAGE_ID}" >"${WORKDIR}/kpkg-install.log" 2>&1 \
        || { fail "kpackagetool6 --install failed:"; cat "${WORKDIR}/kpkg-install.log" >&2; exit 1; }
    [ -f "${SCRIPTS_DIR}/metadata.json" ] || { fail "install did not place metadata.json at ${SCRIPTS_DIR}"; exit 1; }
    ok "install succeeded"

    run_kpkg --list 2>"${WORKDIR}/kpkg-list.log" | grep -qx "$PACKAGE_ID" \
        || { fail "package id not present in kpackagetool6 --list output"; cat "${WORKDIR}/kpkg-list.log" >&2; exit 1; }
    ok "package is listed"

    run_kpkg --upgrade "$UNPACK_DIR/${PACKAGE_ID}" >"${WORKDIR}/kpkg-upgrade.log" 2>&1 \
        || { fail "kpackagetool6 --upgrade failed:"; cat "${WORKDIR}/kpkg-upgrade.log" >&2; exit 1; }
    ok "upgrade succeeded"

    # 11. No files outside the package: everything created by install must
    # live under the installed package directory, and must exactly match
    # what we staged -- nothing extra, nothing missing.
    after_snapshot="${WORKDIR}/home-after.txt"
    find "$TEST_HOME" -type f | LC_ALL=C sort > "$after_snapshot"
    new_files="${WORKDIR}/home-new-files.txt"
    comm -13 "$before_snapshot" "$after_snapshot" > "$new_files"

    unexpected="$(grep -v "^${SCRIPTS_DIR}/" "$new_files" || true)"
    if [ -n "$unexpected" ]; then
        fail "install wrote files outside the installed package directory:"
        printf '%s\n' "$unexpected" >&2
        exit 1
    fi

    expected_installed_files="${WORKDIR}/expected-installed-files.txt"
    (cd "$UNPACK_DIR/${PACKAGE_ID}" && find . -type f | sed "s#^\.#${SCRIPTS_DIR}#" | LC_ALL=C sort) > "$expected_installed_files"
    actual_installed_files="${WORKDIR}/actual-installed-files.txt"
    LC_ALL=C sort "$new_files" > "$actual_installed_files"
    if ! diff "$expected_installed_files" "$actual_installed_files" >"${WORKDIR}/installed-diff.log"; then
        fail "installed file set does not match the package payload exactly:"
        cat "${WORKDIR}/installed-diff.log" >&2
        exit 1
    fi
    ok "no files were written outside the installed package; installed set matches the payload exactly"

    run_kpkg --remove "$PACKAGE_ID" >"${WORKDIR}/kpkg-remove.log" 2>&1 \
        || { fail "kpackagetool6 --remove failed:"; cat "${WORKDIR}/kpkg-remove.log" >&2; exit 1; }
    [ ! -e "$SCRIPTS_DIR" ] || { fail "package directory still present after --remove"; exit 1; }
    ok "remove succeeded, no leftover files"
fi

# ---------------------------------------------------------------------------
# 12. Report artifact info
# ---------------------------------------------------------------------------
ARTIFACT_SIZE="$(stat -c%s "$ARTIFACT")"
ARTIFACT_SHA256="$(sha256sum "$ARTIFACT" | cut -d' ' -f1)"

say "Build complete"
dim "Version:  ${VERSION}"
dim "Artifact: ${ARTIFACT}"
dim "Size:     ${ARTIFACT_SIZE} bytes"
dim "SHA256:   ${ARTIFACT_SHA256}"
ok "dist/$(basename "$ARTIFACT") is ready"

# 13. cleanup of staging/tmp dirs happens via the EXIT trap; dist/ artifact
# is intentionally left behind.
