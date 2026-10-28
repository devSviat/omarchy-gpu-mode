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
    assert d("Hybrid", 1, "Hybrid", True, False, None)["active"] == "standard"
    assert d("Integrated", 1, "Integrated", False, True, None)["active"] == "eco"
    assert d("Hybrid", 0, "Hybrid", True, False, None)["active"] == "standard"
    assert d("Hybrid", 0, "Integrated", True, False, None)["active"] == "eco"
    for runtime in (None, "Vfio"):
        assert d("Hybrid", 0, runtime, True, False, None)["active"] == "ultimate"
        assert d("Hybrid", 1, runtime, False, False, None)["active"] == "eco"
        assert d("Hybrid", 1, runtime, True, True, None)["active"] == "eco"
        assert d("Hybrid", 1, runtime, True, None, None)["active"] == "standard"
        assert d("Hybrid", 1, runtime, True, False, None)["active"] == "standard"


def test_marker_is_active_when_runtime_unknown():
    d = gm.derive_state
    for runtime in (None, "Vfio"):
        assert d("AsusMuxDgpu", 0, runtime, True, False, "standard")["active"] == "standard"
        assert d("Hybrid", 1, runtime, True, False, "ultimate")["active"] == "ultimate"
        assert d("Hybrid", 1, runtime, True, False, "eco")["active"] == "eco"
    assert d("AsusMuxDgpu", 0, "Hybrid", True, False, "eco")["active"] == "standard"


def test_runtime_wins_over_written_mux():
    got = gm.derive_state("Hybrid", 1, "AsusMuxDgpu", True, False, "ultimate")
    assert got["active"] == "ultimate" and got["inconsistent"] is True, got


def test_pending_ultimate_is_not_treated_as_stale():
    got = gm.derive_state("AsusMuxDgpu", 1, "Hybrid", True, False, "standard")
    assert got == {"active": "standard", "configured": "ultimate", "inconsistent": True}, got


def test_bios_mux_flip_is_consistent():
    got = gm.derive_state("Integrated", 0, "AsusMuxDgpu", True, False, None)
    assert got == {"active": "ultimate", "configured": "eco", "inconsistent": False}, got
    got = gm.derive_state("AsusMuxDgpu", 1, "Hybrid", True, False, None)
    assert got == {"active": "standard", "configured": "ultimate", "inconsistent": False}, got


def test_bios_mux_flip_state_has_no_banner():
    base = fakeroot.build(conf_mode="Integrated", mux="0")
    got = gm.state(gm.Root(base), "AsusMuxDgpu", Path("/x"))
    assert got["active"] == "ultimate" and got["inconsistent"] is False, got
    assert got["configured"] == "eco" and got["pendingMode"] is None, got


def test_marker_drives_inconsistent_not_pending_reboot():
    base = fakeroot.build(conf_mode="Hybrid", mux="1", pending="1")
    root = gm.Root(base)
    got = gm.state(root, "Hybrid", Path("/x"))
    assert got["inconsistent"] is False and got["muxPendingReboot"] is True, got
    assert got["pendingMode"] is None
    fakeroot.write(base, gm.PENDING_MARKER.lstrip("/"), "standard\n")
    assert gm.state(root, "Hybrid", Path("/x"))["inconsistent"] is True
    fakeroot.write(base, "etc/supergfxd.conf", '{"mode": "AsusMuxDgpu"}')
    got = gm.state(root, "Hybrid", Path("/x"))
    assert got["pendingMode"] == "ultimate" and got["active"] == "standard", got
    fakeroot.write(base, gm.PENDING_MARKER.lstrip("/"), "bogus\n")
    got = gm.state(root, "Hybrid", Path("/x"))
    assert got["pendingMode"] is None and got["configured"] == "ultimate", got
    assert got["inconsistent"] is False


def test_hook_presence():
    base = fakeroot.build()
    got = gm.state(gm.Root(base), "Hybrid", Path("/x"))
    assert got["ownHookPresent"] is False and got["stockHookPresent"] is False
    fakeroot.write(base, gm.HOOK_PATH.lstrip("/"), "x")
    fakeroot.write(base, gm.STOCK_HOOK_PATH.lstrip("/"), "x")
    got = gm.state(gm.Root(base), "Hybrid", Path("/x"))
    assert got["ownHookPresent"] is True and got["stockHookPresent"] is True


def test_only_the_marker_makes_it_inconsistent():
    for conf in ("Hybrid", "Integrated", "AsusMuxDgpu", None):
        assert gm.derive_state(conf, 1, "Hybrid", True, False, None)["inconsistent"] is False
        assert gm.derive_state(conf, 1, "Hybrid", True, False, "eco")["inconsistent"] is True


def test_unknown_conf():
    got = gm.derive_state(None, 1, "Hybrid", True, False, None)
    assert got["configured"] == "unknown" and got["inconsistent"] is False, got
    assert gm.derive_state("Vfio", 1, "Hybrid", True, False, None)["configured"] == "unknown"


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


def test_dgpu_disable_falls_back_to_wmi():
    base = fakeroot.mkdtemp(prefix="gpumode-wmi-")
    fakeroot.write(base, "sys/devices/platform/asus-nb-wmi/dgpu_disable", "1\n")
    root = gm.Root(base)
    assert gm.dgpu_disabled(root) is True
    assert gm.dgpu_path(root) == root.p(gm.WMI_DGPU)
    base = fakeroot.build(dgpu_disable="0")
    fakeroot.write(base, "sys/devices/platform/asus-nb-wmi/dgpu_disable", "1\n")
    root = gm.Root(base)
    assert gm.dgpu_disabled(root) is False
    assert gm.dgpu_path(root) == root.p(gm.ARMOURY + "/dgpu_disable/current_value")


def test_state_firmware_disabled_without_runtime_is_eco():
    root = gm.Root(fakeroot.build(conf_mode="Integrated", dgpu_disable="1"))
    assert gm.state(root, None, Path("/x"))["active"] == "eco"


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


CONTRACT_KEYS = {"version", "active", "configured", "inconsistent", "pendingMode", "mux",
                 "muxPendingReboot", "dgpuDisabled", "externalConnected", "stockHookPresent",
                 "ownHookPresent", "helper", "error"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
