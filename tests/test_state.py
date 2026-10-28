"""Tests for the `state` command.

Run with:  python3 -I tests/test_state.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakeroot  # noqa: E402

gm = fakeroot.load_module()

CONNECTORS = {
    "card1-HDMI-A-1": "connected",
    "card1-DP-1": "disconnected",
    "card1-eDP-1": "connected",
    "card0-eDP-1": "connected",
}


def test_derive_active():
    d = gm.derive_state
    assert d("Hybrid", 1, "Hybrid", True, False)["active"] == "standard"
    assert d("Integrated", 1, "Integrated", False, False)["active"] == "eco"
    for runtime in ("Hybrid", "Integrated", None):
        assert d("Hybrid", 0, runtime, True, False)["active"] == "ultimate"
    assert d("Hybrid", 1, None, False, False)["active"] == "eco"
    assert d("Hybrid", 1, None, True, False)["active"] == "standard"


def test_stale_conf_is_consistent():
    got = gm.derive_state("AsusMuxDgpu", 1, "Hybrid", True, False)
    assert got == {"active": "standard", "configured": "standard", "inconsistent": False}, got


def test_unrebooted_switch_is_inconsistent():
    assert gm.derive_state("Integrated", 1, "Hybrid", True, False)["inconsistent"] is True
    for conf in ("Hybrid", "Integrated", "AsusMuxDgpu", None):
        assert gm.derive_state(conf, 1, "Hybrid", True, True)["inconsistent"] is True


def test_unknown_conf():
    got = gm.derive_state(None, 1, "Hybrid", True, False)
    assert got["configured"] == "unknown" and got["inconsistent"] is False, got
    assert gm.derive_state("Vfio", 1, "Hybrid", True, False)["configured"] == "unknown"


def test_external_connected():
    root = gm.Root(fakeroot.build(connectors=CONNECTORS))
    assert gm.nvidia_card(root) == "card1"
    assert gm.external_connected(root) == ["HDMI-A-1"]
    root = gm.Root(fakeroot.build(nvidia=False, connectors=CONNECTORS))
    assert gm.nvidia_card(root) is None
    assert gm.external_connected(root) == []


def test_sysfs_readers():
    root = gm.Root(fakeroot.build(mux="0", dgpu_disable="1", pending="1"))
    assert gm.read_mux(root) == 0
    assert gm.mux_pending(root) is True
    assert gm.dgpu_disabled(root) is True
    assert gm.read_conf(root) == {"mode": "Hybrid"}
    bare = gm.Root(fakeroot.mkdtemp(prefix="gpumode-empty-"))
    assert gm.read_mux(bare) is None and gm.mux_path(bare) is None
    assert gm.mux_pending(bare) is False
    assert gm.dgpu_disabled(bare) is None


def test_state_without_supergfxctl():
    root = gm.Root(fakeroot.build(connectors=CONNECTORS))
    got = gm.state(root, None, Path("/nonexistent/gpu-mode"))
    assert got["active"] == "standard" and got["error"] == "", got
    assert got["version"] == 1 and got["mux"] == 1
    assert got["externalConnected"] == ["HDMI-A-1"]


def test_state_reports_helper_status():
    root = gm.Root(fakeroot.build())
    tmp = Path(fakeroot.mkdtemp(prefix="gpumode-helper-"))
    repo_file, installed = tmp / "repo", tmp / "installed"
    repo_file.write_bytes(b"one")
    assert gm.helper_status(repo_file, installed) == "missing"
    installed.write_bytes(b"two")
    assert gm.helper_status(repo_file, installed) == "outdated"
    installed.write_bytes(b"one")
    assert gm.helper_status(repo_file, installed) == "current"
    repo_file.unlink()
    assert gm.helper_status(repo_file, installed) == "outdated"
    # state() looks for the installed helper under the fake root, where none exists
    repo_file.write_bytes(b"one")
    assert gm.state(root, "Hybrid", repo_file)["helper"] == "missing"
    helper = Path(root.p(str(gm.INSTALLED_HELPER)))
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"one")
    assert gm.state(root, "Hybrid", repo_file)["helper"] == "current"
    helper.write_bytes(b"other")
    assert gm.state(root, "Hybrid", repo_file)["helper"] == "outdated"


def test_state_bad_conf():
    root = gm.Root(fakeroot.build(conf_text="{not json"))
    got = gm.state(root, "Hybrid", Path("/nonexistent/gpu-mode"))
    assert got["configured"] == "unknown" and got["error"], got
    root = gm.Root(fakeroot.build(conf_text="[1]"))
    assert gm.state(root, "Hybrid", Path("/x"))["error"]


def test_non_string_mode_is_unknown_with_error():
    for text in ('{"mode": []}', '{"mode": {}}', '{"mode": 3}', '{}'):
        root = gm.Root(fakeroot.build(conf_text=text))
        got = gm.state(root, "Hybrid", Path("/x"))
        assert got["configured"] == "unknown" and got["error"], (text, got)


def test_deeply_nested_conf_does_not_raise():
    root = gm.Root(fakeroot.build(conf_text="[" * 100000 + "]" * 100000))
    got = gm.state(root, "Hybrid", Path("/x"))
    assert got["configured"] == "unknown" and got["error"], got


def test_runtime_mode_failures_are_none():
    assert gm.runtime_mode(timeout=0.2, cmd=["/usr/bin/sleep", "5"]) is None
    assert gm.runtime_mode(cmd=["/usr/bin/false"]) is None
    assert gm.runtime_mode(cmd=["/nonexistent/supergfxctl", "-g"]) is None
    assert gm.runtime_mode(cmd=["/usr/bin/echo", "Hybrid"]) == "Hybrid"


def test_main_state_prints_contract_json():
    import contextlib
    import io
    import json
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = gm.main(["state"])
    assert code == 0
    out = buf.getvalue()
    assert out.count("\n") == 1
    assert set(json.loads(out)) == CONTRACT_KEYS, out


def test_main_state_survives_internal_failure():
    import contextlib
    import io
    import json
    original = gm.state
    gm.state = lambda *a: 1 / 0
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gm.main(["state"])
    finally:
        gm.state = original
    got = json.loads(buf.getvalue())
    assert code == 0 and set(got) == CONTRACT_KEYS and got["error"], got


CONTRACT_KEYS = {"version", "active", "configured", "inconsistent", "mux", "muxPendingReboot",
                 "dgpuDisabled", "externalConnected", "stockHookPresent", "helper", "error"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
