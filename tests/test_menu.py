"""Tests for bin/gpu-mode-menu.

Run with:  python3 -I tests/test_menu.py
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "bin" / "gpu-mode-menu"

TEMPLATE = """{
  // Extend the Quickshell Omarchy menu with JSONC.
  //
  // Examples:
  // "personal.notes": {"icon":"x","label":"Notes","action":"true"},

}
"""

WITH_ENTRY = """{
  // comment
  "personal.notes": {"icon":"x","label":"Notes","action":"true"},
}
"""


def strip_jsonc(text):
    text = "\n".join(l for l in text.split("\n") if not re.match(r"^\s*//", l))
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def run(command, path):
    return subprocess.run(
        [sys.executable, "-I", str(TOOL), command, "--file", str(path)],
        capture_output=True, text=True,
    )


def tmpfile(content):
    d = tempfile.TemporaryDirectory()
    p = Path(d.name) / "omarchy-menu.jsonc"
    if content is not None:
        p.write_text(content)
    return d, p


def test_install_into_template():
    d, p = tmpfile(TEMPLATE)
    with d:
        r = run("install", p)
        assert r.returncode == 0, r.stderr
        data = strip_jsonc(p.read_text())
        assert list(data) == ["trigger.hardware.hybrid-gpu"], data
        row = data["trigger.hardware.hybrid-gpu"]
        assert row["label"] == "GPU Mode"
        assert row["when"] == "omarchy-hw-hybrid-gpu"
        assert row["action"] == "omarchy-shell shell summon sviat.gpu-mode '{}'"
        assert row["icon"]


def test_install_idempotent():
    d, p = tmpfile(TEMPLATE)
    with d:
        run("install", p)
        once = p.read_text()
        assert run("install", p).returncode == 0
        assert p.read_text() == once
        assert once.count("// >>> sviat.gpu-mode") == 1
        assert once.count("// <<< sviat.gpu-mode") == 1


def test_remove_restores():
    for original in (TEMPLATE, WITH_ENTRY):
        d, p = tmpfile(original)
        with d:
            run("install", p)
            assert run("remove", p).returncode == 0
            assert p.read_bytes() == original.encode()


def test_preserves_user_entries():
    d, p = tmpfile(WITH_ENTRY)
    with d:
        run("install", p)
        data = strip_jsonc(p.read_text())
        assert set(data) == {"personal.notes", "trigger.hardware.hybrid-gpu"}
        run("remove", p)
        assert set(strip_jsonc(p.read_text())) == {"personal.notes"}


def test_backup_before_change():
    d, p = tmpfile(TEMPLATE)
    with d:
        run("install", p)
        baks = list(p.parent.glob("omarchy-menu.jsonc.*.bak"))
        assert len(baks) == 1, baks
        assert baks[0].read_text() == TEMPLATE


def test_missing_file_created():
    d, p = tmpfile(None)
    with d:
        assert run("install", p).returncode == 0
        assert list(strip_jsonc(p.read_text())) == ["trigger.hardware.hybrid-gpu"]
        assert not list(p.parent.glob("*.bak"))
        assert run("remove", p).returncode == 0
        assert strip_jsonc(p.read_text()) == {}


def test_remove_missing_file_is_noop():
    d, p = tmpfile(None)
    with d:
        assert run("remove", p).returncode == 0
        assert not p.exists()


def test_unparseable_shape_rejected():
    d, p = tmpfile("[]\n")
    with d:
        r = run("install", p)
        assert r.returncode != 0
        assert p.read_text() == "[]\n"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"{len(tests)} passed")
