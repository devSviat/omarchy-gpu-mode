#!/bin/bash

# Root-side install for the GPU mode plugin: the privileged helper and its
# polkit action. Run with sudo. Never changes the GPU mode.
#
#   sudo ./install-root.sh           install helper and policy, then normalize
#   sudo ./install-root.sh --remove  reset hotplug_type, remove helper, policy, drop-in and the old sleep hook

set -euo pipefail

CONF="/etc/supergfxd.conf"
HELPER_DIR="/usr/local/libexec/omarchy-gpu-mode"
HELPER="$HELPER_DIR/gpu-mode"
POLICY="/usr/share/polkit-1/actions/dev.sviat.gpu-mode.policy"
OLD_HOOK="/usr/lib/systemd/system-sleep/omarchy-gpu-mode-igpu"
DROPIN="/etc/systemd/system/supergfxd.service.d/delay-start.conf"

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

refuse_remove_in_eco() {
  if conf_is_integrated "$1"; then
    echo "GPU Mode: switch to Standard or Ultimate before removing (Eco keeps the NVIDIA GPU disabled in firmware)." >&2
    return 1
  fi
}

# The repo is user-writable, so each source is opened once, without following a
# symlink at any path component, and installed from that root-owned copy.
stage_copy() {
  /usr/bin/python3 -I -c '
import os, stat, sys
base, rel, dest = sys.argv[1:4]
fd = None
try:
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    parts = rel.split("/")
    for part in parts[:-1]:
        nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = nxt
    src = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(src, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            sys.exit(f"install-root.sh: {base}/{rel} is not a regular file")
        data = handle.read()
    with open(dest, "xb") as out:
        out.write(data)
except OSError as exc:
    sys.exit(f"install-root.sh: cannot read {base}/{rel}: {exc.strerror}")
finally:
    if fd is not None:
        os.close(fd)
' "$1" "$2" "$3"
}

# $1 is an alternative root for tests; empty means /. Sets dropin_removed.
remove_root_files() {
  local root="$1"
  dropin_removed="false"
  refuse_remove_in_eco "$root$CONF" || return 1
  # The stock toggle cannot leave Eco while supergfxd uses "Asus", so it is reset first.
  if [[ ! -x "$root$HELPER" ]] || ! "$root$HELPER" restore-hotplug; then
    echo "GPU Mode: could not reset hotplug_type in $CONF. Run: sudo $0 (to update the helper), then --remove again." >&2
    return 1
  fi
  rm -f "$root$HELPER" "$root$POLICY" "$root$OLD_HOOK"
  rmdir "$root$HELPER_DIR" 2>/dev/null || true
  if [[ -e "$root$DROPIN" ]]; then
    rm -f "$root$DROPIN"
    rmdir "$(dirname "$root$DROPIN")" 2>/dev/null || true
    dropin_removed="true"
  fi
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  remove_root_files "" || exit 1
  if [[ $dropin_removed == "true" ]] && ! /usr/bin/systemctl daemon-reload; then
    echo "GPU Mode: files removed, but systemctl daemon-reload failed; run it manually." >&2
    exit 1
  fi
  echo "Reset hotplug_type to None and removed the GPU mode helper, policy and drop-in, and the old sleep hook if present."
  exit 0
fi

stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
stage_copy "$REPO" libexec/gpu-mode "$stage/gpu-mode"
stage_copy "$REPO" polkit/dev.sviat.gpu-mode.policy "$stage/policy"

install -d -o root -g root -m 0755 "$HELPER_DIR"
install -o root -g root -m 0755 "$stage/gpu-mode" "$HELPER"
install -o root -g root -m 0644 "$stage/policy" "$POLICY"

"$HELPER" normalize
echo "Installed $HELPER and $POLICY."
echo "Reboot to finish (Eco uses the new firmware power-off from the next boot)."
