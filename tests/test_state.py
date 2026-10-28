"""Tests for the `state` command.

Run with:  python3 -I tests/test_state.py
"""

import sys
import tempfile
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
    bare = gm.Root(tempfile.mkdtemp(prefix="gpumode-empty-"))
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
    tmp = Path(tempfile.mkdtemp(prefix="gpumode-helper-"))
    repo_file, installed = tmp / "repo", tmp / "installed"
    repo_file.write_bytes(b"one")
    assert gm.helper_status(repo_file, installed) == "missing"
    installed.write_bytes(b"two")
    assert gm.helper_status(repo_file, installed) == "outdated"
    installed.write_bytes(b"one")
    assert gm.helper_status(repo_file, installed) == "current"
    assert gm.state(root, "Hybrid", repo_file)["helper"] in ("missing", "outdated", "current")


def test_state_bad_conf():
    root = gm.Root(fakeroot.build(conf_text="{not json"))
    got = gm.state(root, "Hybrid", Path("/nonexistent/gpu-mode"))
    assert got["configured"] == "unknown" and got["error"], got
    root = gm.Root(fakeroot.build(conf_text="[1]"))
    assert gm.state(root, "Hybrid", Path("/x"))["error"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
