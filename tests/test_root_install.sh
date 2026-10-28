#!/bin/bash
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY="$REPO/polkit/dev.sviat.gpu-mode.policy"
SCRIPT="$REPO/install-root.sh"
HELPER=/usr/local/libexec/omarchy-gpu-mode/gpu-mode
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

policy_is_valid_xml() { xmllint --noout "$POLICY"; }
policy_exec_path() { grep -qF "<annotate key=\"org.freedesktop.policykit.exec.path\">$HELPER</annotate>" "$POLICY"; }
policy_action_id() { grep -qF 'id="dev.sviat.gpu-mode.apply"' "$POLICY"; }
policy_defaults() {
  grep -qF '<allow_any>no</allow_any>' "$POLICY" &&
    grep -qF '<allow_inactive>no</allow_inactive>' "$POLICY" &&
    grep -qF '<allow_active>auth_admin</allow_active>' "$POLICY"
}
refuses_without_root() {
  [[ -f $SCRIPT ]] || return 1
  [[ $EUID -ne 0 ]] || return 0
  local out rc
  out="$(bash "$SCRIPT" 2>&1)" && return 1
  rc=$?
  [[ $rc -ne 0 && -n "$out" ]]
}
unknown_option_rejected() { [[ -f $SCRIPT ]] && ! bash "$SCRIPT" --bogus; }
help_mentions_remove() { bash "$SCRIPT" --help | grep -q -- '--remove'; }
integrated_conf_detected() (
  local d f
  d="$(mktemp -d)"
  printf '{"mode":"Integrated"}' >"$d/a"
  printf '{"mode":"Hybrid"}' >"$d/b"
  printf 'garbage' >"$d/c"
  # shellcheck disable=SC1090
  source "$SCRIPT"
  conf_is_integrated "$d/a" && ! conf_is_integrated "$d/b" &&
    ! conf_is_integrated "$d/c" && ! conf_is_integrated "$d/missing"
  f=$?
  rm -rf "$d"
  return $f
)
shellcheck_clean() {
  command -v shellcheck >/dev/null || return 0
  shellcheck "$SCRIPT"
}

check "policy is valid XML" policy_is_valid_xml
check "policy exec.path is the installed helper" policy_exec_path
check "policy action id" policy_action_id
check "policy defaults" policy_defaults
check "install-root.sh refuses without root" refuses_without_root
check "install-root.sh rejects unknown option" unknown_option_rejected
check "--help mentions --remove" help_mentions_remove
check "Integrated conf detection" integrated_conf_detected
check "shellcheck (skipped if absent)" shellcheck_clean

exit "$failed"
