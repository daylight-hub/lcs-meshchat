#!/bin/sh
# Rebuild the transport console from source and check that the LCS additions
# still attach to it.
#
#   sh tools/console/run_tests.sh
#
# Requires playwright with chromium. Run this after touching anything in
# tools/console/ or after vendoring a new console build.
set -e
cd "$(dirname "$0")/../.."

echo "== selector contract =="
python3 tools/console/build_console.py --verify

echo
echo "== rebuild =="
python3 tools/console/build_console.py

echo
echo "== console extras (preset dropdown, warnings) =="
node tools/console/test_console_extras.mjs

echo
echo "== bridge discovery (same origin, the Docker path) =="
node tools/console/test_bridge_discovery.mjs

echo
echo "== .local sweep candidates =="
node tools/console/test_local_sweep.mjs

echo
echo "all console tests passed"
