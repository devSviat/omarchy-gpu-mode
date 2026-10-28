#!/bin/bash

# Root-side install for the GPU mode plugin: the privileged helper and its
# polkit action. Run with sudo. Never changes the GPU mode.
#
#   sudo ./install-root.sh           install helper and policy, then normalize
#   sudo ./install-root.sh --remove  remove helper, policy, sleep hook and drop-in

set -euo pipefail

usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; started = 1; next } started { exit }' "${BASH_SOURCE[0]}"
}

conf_is_integrated() {
  /usr/bin/python3 -I -c '
import json, sys
try:
    with open(sys.argv[1]) as f:
        sys.exit(0 if json.load(f).get("mode") == "Integrated" else 1)
except Exception:
    sys.exit(1)
' "$1"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER_DIR="/usr/local/libexec/omarchy-gpu-mode"
HELPER="$HELPER_DIR/gpu-mode"
POLICY="/usr/share/polkit-1/actions/dev.sviat.gpu-mode.policy"
HOOK="/usr/lib/systemd/system-sleep/omarchy-gpu-mode-igpu"
DROPIN="/etc/systemd/system/supergfxd.service.d/delay-start.conf"

remove="false"

while (( $# > 0 )); do
  case "$1" in
  --remove) remove="true" ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "install-root.sh: unknown option: $1" >&2
    exit 1
    ;;
  esac
  shift
done

if (( EUID != 0 )); then
  echo "install-root.sh: must run as root (use sudo)" >&2
  exit 1
fi

if [[ "$remove" == "true" ]]; then
  if conf_is_integrated /etc/supergfxd.conf; then
    echo "GPU Mode: switch to Standard or Ultimate before removing (Eco needs the sleep hook)." >&2
    exit 1
  fi
  rm -f "$HELPER" "$POLICY" "$HOOK"
  rmdir "$HELPER_DIR" 2>/dev/null || true
  if [[ -e "$DROPIN" ]]; then
    rm -f "$DROPIN"
    rmdir "$(dirname "$DROPIN")" 2>/dev/null || true
    if ! systemctl daemon-reload; then
      echo "GPU Mode: files removed, but systemctl daemon-reload failed; run it manually." >&2
      exit 1
    fi
  fi
  echo "Removed the GPU mode helper, policy, sleep hook and drop-in."
  exit 0
fi

if [[ ! -f "$REPO/libexec/gpu-mode" || -L "$REPO/libexec/gpu-mode" ]]; then
  echo "install-root.sh: $REPO/libexec/gpu-mode is not a regular file" >&2
  exit 1
fi
if [[ ! -f "$REPO/polkit/dev.sviat.gpu-mode.policy" ]]; then
  echo "install-root.sh: $REPO/polkit/dev.sviat.gpu-mode.policy is missing" >&2
  exit 1
fi

install -d -o root -g root -m 0755 "$HELPER_DIR"
install -o root -g root -m 0755 "$REPO/libexec/gpu-mode" "$HELPER"
install -o root -g root -m 0644 "$REPO/polkit/dev.sviat.gpu-mode.policy" "$POLICY"

"$HELPER" normalize
echo "Installed $HELPER and $POLICY."
