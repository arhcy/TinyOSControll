#!/usr/bin/env bash
# Agent container entrypoint: make hostcmd executable, then run the daemon.
set -euo pipefail

chmod +x /opt/tinyos/hostcmd.sh 2>/dev/null || true

exec python3 /opt/tinyos/agent.py
