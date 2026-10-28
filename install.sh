#!/bin/bash

# User-level install for the GPU mode plugin: link the checkout in as the
# plugin, enable it, and add the menu row. Never touches the GPU mode and
# puts nothing on the bar. The root step is printed at the end.
#
#   ./install.sh           link, enable, add the menu row
#   ./install.sh --remove  remove the menu row, disable and unlink (refuses in Eco)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="sviat.gpu-mode"
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"

# shellcheck source=install-root.sh
source "$REPO/install-root.sh"

usage() {
  awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; started = 1; next } started { exit }' "${BASH_SOURCE[0]}"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

remove="false"

while (( $# > 0 )); do
  case "$1" in
  --remove) remove="true" ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "install.sh: unknown option: $1" >&2
    exit 1
    ;;
  esac
  shift
done

if [[ $remove == "true" ]]; then
  refuse_remove_in_eco /etc/supergfxd.conf || exit 1
  "$REPO/bin/gpu-mode-menu" remove
  omarchy plugin disable "$PLUGIN_ID" || true
  if [[ -L $PLUGIN_DIR ]]; then
    rm "$PLUGIN_DIR"
    echo "  plugin   removed $PLUGIN_DIR"
  fi
  echo
  echo "If the root files are still installed, remove them with:"
  echo "  sudo $REPO/install-root.sh --remove"
  exit 0
fi

echo "Placing files from $REPO"

if [[ -e $PLUGIN_DIR && ! -L $PLUGIN_DIR ]]; then
  echo "  plugin   $PLUGIN_DIR already exists and is not a symlink, leaving it"
else
  mkdir -p "$(dirname "$PLUGIN_DIR")"
  ln -sfn "$REPO" "$PLUGIN_DIR"
  echo "  plugin   $PLUGIN_DIR"
fi

# The shell caches manifests; a stale one would place the plugin on the bar.
omarchy-shell shell rescanPlugins >/dev/null ||
  echo "GPU Mode: shell not running, skipped plugin rescan" >&2
"$REPO/bin/gpu-mode-menu" install
if ! omarchy plugin enable "$PLUGIN_ID"; then
  echo "GPU Mode: could not enable the plugin (is the shell running?)" >&2
fi

echo
echo "Root step (installs the helper and polkit action):"
echo "  sudo $REPO/install-root.sh"
