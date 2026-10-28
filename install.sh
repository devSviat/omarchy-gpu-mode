#!/bin/bash

# User-level install for the GPU mode plugin: link the checkout in as the
# plugin, enable it, and add the menu row. Never touches the GPU mode and
# puts nothing on the bar. The root step is printed at the end.
#
#   ./install.sh           link, enable, add the menu row
#   ./install.sh --remove  remove the menu row, disable and unlink

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="sviat.gpu-mode"
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"

remove="false"

while (( $# > 0 )); do
  case "$1" in
  --remove) remove="true" ;;
  -h | --help)
    sed -n '3,9p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
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
  "$REPO/bin/gpu-mode-menu" remove
  omarchy plugin disable "$PLUGIN_ID" || true
  if [[ -L $PLUGIN_DIR ]]; then
    rm "$PLUGIN_DIR"
    echo "  plugin   removed $PLUGIN_DIR"
  fi
  echo
  echo "Root files stay until you remove them (in Standard or Ultimate; it refuses in Eco):"
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

omarchy plugin enable "$PLUGIN_ID"
"$REPO/bin/gpu-mode-menu" install

echo
echo "Root step (installs the helper and polkit action):"
echo "  sudo $REPO/install-root.sh"
