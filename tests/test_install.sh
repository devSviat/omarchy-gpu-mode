#!/bin/bash
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO/install.sh"
failed=0

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "ok   $name"
  else
    echo "FAIL $name"
    failed=1
  fi
}

remove_refused_in_eco() (
  local d out rc=0
  d="$(mktemp -d)"
  printf '{"mode":"Integrated"}' >"$d/eco"
  printf '{"mode":"Hybrid"}' >"$d/standard"
  printf '{"mode":"AsusMuxDgpu"}' >"$d/ultimate"
  printf 'garbage' >"$d/broken"
  # shellcheck disable=SC1090
  source "$SCRIPT"
  set +e
  out="$(refuse_remove_in_eco "$d/eco" 2>&1)" && rc=1
  [[ $out == "GPU Mode: switch to Standard or Ultimate before removing (Eco keeps the NVIDIA GPU disabled in firmware)." ]] || rc=1
  for conf in standard ultimate broken missing; do
    refuse_remove_in_eco "$d/$conf" || rc=1
  done
  rm -rf "$d"
  return $rc
)
refusal_comes_first() {
  grep -A1 -F 'if [[ $remove == "true" ]]; then' "$SCRIPT" |
    grep -qF 'refuse_remove_in_eco /etc/supergfxd.conf || exit 1'
}
menu_row_before_enable() {
  local menu enable
  menu="$(grep -nF '"$REPO/bin/gpu-mode-menu" install' "$SCRIPT" | cut -d: -f1)"
  enable="$(grep -nF 'omarchy plugin enable' "$SCRIPT" | cut -d: -f1)"
  [[ -n $menu && -n $enable ]] && ((menu < enable))
}
enable_failure_is_not_fatal() {
  grep -qF 'if ! omarchy plugin enable "$PLUGIN_ID"; then' "$SCRIPT"
}
help_works() { bash "$SCRIPT" --help | grep -q -- '--remove'; }
shellcheck_clean() {
  command -v shellcheck >/dev/null || return 0
  shellcheck -x "$SCRIPT"
}

check "install.sh --remove refuses in Eco only" remove_refused_in_eco
check "the Eco refusal runs before any removal" refusal_comes_first
check "menu row is installed before enabling" menu_row_before_enable
check "a failed enable does not stop the install" enable_failure_is_not_fatal
check "install.sh --help" help_works
check "shellcheck (skipped if absent)" shellcheck_clean

exit "$failed"
