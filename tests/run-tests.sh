#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

printf '\n==> Python tests\n'
python3 -m unittest discover -s tests/python -p 'test_*.py' -v

printf '\n==> JavaScript tests\n'
node --test tests/js/*.test.js
