"""Tests for the `apply` and `normalize` commands.

Run with:  python3 -I tests/test_apply.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakeroot  # noqa: E402

gm = fakeroot.load_module()


def snap(base, *paths):
    out = {}
    for rel in paths:
        p = Path(base) / rel.lstrip("/")
        out[rel] = (p.read_bytes(), p.stat().st_mode & 0o777) if p.is_file() else None
    return out


def mux_file(base):
    return Path(base) / fakeroot.ARMOURY / "gpu_mux_mode/current_value"


def dgpu_file(base):
    return Path(base) / fakeroot.ARMOURY / "dgpu_disable/current_value"


def conf_file(base):
    return Path(base) / "etc/supergfxd.conf"


def put(base, rel, text, mode):
    p = fakeroot.write(base, rel.lstrip("/"), text)
    p.chmod(mode)
    return p


def old_hook(base):
    return Path(base, gm.HOOK_PATH.lstrip("/"))


def dropin(base):
    return Path(base, gm.DROPIN_PATH.lstrip("/"))


def apply(base, mode, **kwargs):
    kwargs.setdefault("owner_uid", os.getuid())
    kwargs.setdefault("runtime", lambda: None)
    gm.apply_mode(gm.Root(base), mode, **kwargs)


def run_apply(base, mode):
    calls = []
    apply(base, mode, reload=lambda: calls.append(1))
    return calls


def raises_apply(fn):
    try:
        fn()
    except gm.ApplyError:
        return True
    return False


def test_target_config():
    conf = {"mode": "Hybrid", "hotplug_type": "None", "x": [1]}
    for mode, conf_mode in gm.MODES.items():
        assert gm.target_config(conf, mode) == {"mode": conf_mode, "hotplug_type": "Asus", "x": [1]}
    assert conf == {"mode": "Hybrid", "hotplug_type": "None", "x": [1]}
    for vfio in (True, False):
        old = {"mode": "Integrated", "vfio_enable": vfio}
        assert gm.target_config(old, "standard")["vfio_enable"] is vfio
        assert gm.target_config(old, "eco")["vfio_enable"] is vfio
    assert "vfio_enable" not in gm.target_config({"mode": "Hybrid"}, "eco")


def test_standard_to_eco():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    conf_file(base).write_text(json.dumps({"mode": "Hybrid", "hotplug_type": "None", "keep": 7}))
    put(base, gm.STOCK_HOOK_PATH, "#!/bin/bash\n", 0o755)
    put(base, gm.HOOK_PATH, "old hook", 0o755)
    calls = run_apply(base, "eco")
    got = json.loads(conf_file(base).read_text())
    assert got == {"mode": "Integrated", "hotplug_type": "Asus", "keep": 7}
    assert dgpu_file(base).read_text() == "0\n"
    assert mux_file(base).read_text() == "1\n"
    assert not old_hook(base).exists()
    assert dropin(base).read_text() == gm.DROPIN_SOURCE
    assert dropin(base).stat().st_mode & 0o777 == 0o644
    assert conf_file(base).stat().st_mode & 0o777 == 0o644
    assert not Path(base, gm.STOCK_HOOK_PATH.lstrip("/")).exists()
    assert calls == [1]


def test_eco_to_ultimate():
    base = fakeroot.build(conf_mode="Integrated", mux="1")
    run_apply(base, "eco")
    fakeroot.write(base, fakeroot.ARMOURY + "/gpu_mux_mode/current_value", "1\n")
    calls = run_apply(base, "ultimate")
    assert json.loads(conf_file(base).read_text())["mode"] == "AsusMuxDgpu"
    assert mux_file(base).read_text() == "0"
    assert not dropin(base).exists() and not old_hook(base).exists()
    assert calls == [1]


def test_ultimate_to_eco_single_step():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="0")
    run_apply(base, "eco")
    assert mux_file(base).read_text() == "1"
    assert json.loads(conf_file(base).read_text())["mode"] == "Integrated"
    assert dropin(base).is_file() and not old_hook(base).exists()


def test_every_mode_removes_the_old_hook_and_keeps_the_stock_one_outside_eco():
    for mode in gm.MODES:
        base = fakeroot.build(conf_mode="Hybrid", mux="1")
        put(base, gm.HOOK_PATH, "old hook", 0o755)
        put(base, gm.STOCK_HOOK_PATH, "stock", 0o755)
        run_apply(base, mode)
        assert not old_hook(base).exists(), mode
        stock = Path(base, gm.STOCK_HOOK_PATH.lstrip("/"))
        assert stock.exists() is (mode != "eco"), mode


def test_no_sleep_hook_is_shipped():
    assert not hasattr(gm, "HOOK_SOURCE")


def recording_writes(fn):
    writes = []
    original = gm._write_attr

    def record(path, value):
        writes.append((Path(path).parent.name if Path(path).name == "current_value"
                       else Path(path).name, value))
        original(path, value)

    gm._write_attr = record
    try:
        fn()
    finally:
        gm._write_attr = original
    return writes


def test_eco_never_writes_dgpu_disable():
    for conf_mode, mux in (("Hybrid", "1"), ("AsusMuxDgpu", "0"), ("Integrated", "1")):
        base = fakeroot.build(conf_mode=conf_mode, mux=mux)
        writes = recording_writes(lambda: run_apply(base, "eco"))
        assert all(name != "dgpu_disable" for name, _ in writes), writes
        assert dgpu_file(base).read_text() == "0\n"


def test_leaving_eco_clears_dgpu_disable_before_mux():
    base = fakeroot.build(conf_mode="Integrated", mux="1", dgpu_disable="1", nvidia=False)
    writes = recording_writes(lambda: run_apply(base, "ultimate"))
    assert writes == [("dgpu_disable", "0"), ("gpu_mux_mode", "0")], writes
    assert json.loads(conf_file(base).read_text())["mode"] == "AsusMuxDgpu"
    base = fakeroot.build(conf_mode="Integrated", mux="1", dgpu_disable="1", nvidia=False)
    writes = recording_writes(lambda: run_apply(base, "standard"))
    assert writes == [("dgpu_disable", "0")], writes
    assert dgpu_file(base).read_text() == "0"


def test_leaving_eco_uses_wmi_dgpu_disable_fallback():
    base = fakeroot.build(conf_mode="Integrated", mux="1", nvidia=False)
    dgpu_file(base).unlink()
    wmi = fakeroot.write(base, gm.WMI_DGPU.lstrip("/"), "1\n")
    run_apply(base, "standard")
    assert wmi.read_text() == "0"


def test_rollback_restores_dgpu_disable_after_mux():
    base = fakeroot.build(conf_mode="Integrated", mux="1", dgpu_disable="1", nvidia=False)
    paths = ("etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value",
             fakeroot.ARMOURY + "/dgpu_disable/current_value")
    before = snap(base, *paths)
    writes = recording_writes(lambda: fail_conf_write_once(lambda: run_apply(base, "ultimate")))
    assert writes == [("dgpu_disable", "0"), ("gpu_mux_mode", "0"),
                      ("gpu_mux_mode", "1\n"), ("dgpu_disable", "1\n")], writes
    assert {k: v[0].strip() for k, v in snap(base, *paths).items()} == \
        {k: v[0].strip() for k, v in before.items()}


def test_rollback_restores_dgpu_disable_even_when_readback_lies():
    base = fakeroot.build(conf_mode="Integrated", mux="1", dgpu_disable="1", nvidia=False)
    original = gm._write_attr
    restored = []

    def lying(path, value):
        original(path, value)
        if Path(path).parent.name == "dgpu_disable":
            restored.append(value)
            Path(path).write_text("1\n")

    gm._write_attr = lying
    try:
        fail_conf_write_once(lambda: run_apply(base, "standard"))
    finally:
        gm._write_attr = original
    assert restored == ["0", "1\n"], restored


def test_apply_refuses_bad_conf_without_side_effects():
    for kwargs in ({"conf_text": "{not json"}, {"conf_text": "[]"}):
        base = fakeroot.build(mux="0", **kwargs)
        put(base, gm.HOOK_PATH, "old hook", 0o755)
        paths = ("etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value",
                 gm.HOOK_PATH, gm.DROPIN_PATH)
        before = snap(base, *paths)
        assert raises_apply(lambda: run_apply(base, "standard"))
        assert snap(base, *paths) == before
    base = fakeroot.build(mux="0")
    conf_file(base).unlink()
    before = snap(base, fakeroot.ARMOURY + "/gpu_mux_mode/current_value")
    assert raises_apply(lambda: run_apply(base, "eco"))
    assert snap(base, fakeroot.ARMOURY + "/gpu_mux_mode/current_value") == before
    assert not Path(base, gm.HOOK_PATH.lstrip("/")).exists()


def test_apply_rejects_unknown_mode():
    base = fakeroot.build()
    assert raises_apply(lambda: run_apply(base, "turbo"))


def test_rollback_on_failure():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="0")
    put(base, gm.STOCK_HOOK_PATH, "stock", 0o755)
    put(base, gm.DROPIN_PATH, "old dropin", 0o644)
    put(base, gm.HOOK_PATH, "old hook", 0o755)
    paths = ("etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value",
             gm.HOOK_PATH, gm.DROPIN_PATH, gm.STOCK_HOOK_PATH)
    before = snap(base, *paths)
    original = gm._atomic_write
    state = {"failed": False}

    def failing(path, data, mode):
        if str(path).endswith("supergfxd.conf") and not state["failed"]:
            state["failed"] = True
            raise OSError("disk full")
        return original(path, data, mode)

    gm._atomic_write = failing
    reloads = []
    try:
        assert raises_apply(lambda: apply(base, "eco", reload=lambda: reloads.append(1)))
    finally:
        gm._atomic_write = original
    assert state["failed"]
    assert snap(base, *paths) == before
    assert reloads == [1]


def test_mux_written_when_pending_despite_readback():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="1", pending="1")
    writes = []
    original = gm._write_attr
    gm._write_attr = lambda path, value: writes.append(value)
    try:
        run_apply(base, "standard")
    finally:
        gm._write_attr = original
    assert writes == ["1"]


def test_rollback_restores_mux_even_when_readback_lies():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="0")
    original_write, lying = gm._write_attr, None
    state = {"n": 0}

    def write(path, value):
        state["n"] += 1
        original_write(path, value)
        if state["n"] == 1:
            Path(path).write_text("0")

    original_atomic = gm._atomic_write

    def failing(path, data, mode):
        if str(path).endswith("supergfxd.conf") and not state.get("f"):
            state["f"] = True
            raise OSError("boom")
        return original_atomic(path, data, mode)

    gm._write_attr, gm._atomic_write = write, failing
    try:
        assert raises_apply(lambda: run_apply(base, "standard"))
    finally:
        gm._write_attr, gm._atomic_write = original_write, original_atomic
    assert state["n"] == 2
    assert mux_file(base).read_text().strip() == "0"


def test_reload_failure_rolls_back():
    base = fakeroot.build(conf_mode="Hybrid", mux="0")
    paths = ("etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value",
             gm.HOOK_PATH, gm.DROPIN_PATH)
    before = snap(base, *paths)

    def bad():
        raise RuntimeError("reload broke")

    try:
        apply(base, "eco", reload=bad)
        raise AssertionError("no error")
    except gm.ApplyError as exc:
        assert "reload broke" in str(exc)
    assert snap(base, *paths) == before


def test_rollback_continues_after_mux_restore_failure():
    base = fakeroot.build(conf_mode="Hybrid", mux="0")
    put(base, gm.DROPIN_PATH, "old", 0o644)
    original_write, original_atomic = gm._write_attr, gm._atomic_write
    n = {"w": 0, "c": 0}

    def write(path, value):
        n["w"] += 1
        if n["w"] == 2:
            raise OSError("mux restore broke")
        original_write(path, value)

    def failing(path, data, mode):
        if str(path).endswith("supergfxd.conf") and n["c"] == 0:
            n["c"] = 1
            raise OSError("conf broke")
        return original_atomic(path, data, mode)

    gm._write_attr, gm._atomic_write = write, failing
    try:
        apply(base, "eco")
        raise AssertionError("no error")
    except gm.ApplyError as exc:
        msg = str(exc)
    finally:
        gm._write_attr, gm._atomic_write = original_write, original_atomic
    assert "conf broke" in msg and "mux restore broke" in msg
    assert Path(base, gm.DROPIN_PATH.lstrip("/")).read_text() == "old"
    assert not Path(base, gm.HOOK_PATH.lstrip("/")).exists()


def test_conf_mode_restored():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    conf_file(base).chmod(0o600)
    original = gm._install

    def bad(*a):
        raise OSError("x")

    gm._install = bad
    try:
        assert raises_apply(lambda: run_apply(base, "eco"))
    finally:
        gm._install = original
    assert conf_file(base).stat().st_mode & 0o777 == 0o600


def test_idempotent():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    run_apply(base, "eco")
    paths = ("etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value",
             gm.HOOK_PATH, gm.DROPIN_PATH)
    first = snap(base, *paths)
    calls = run_apply(base, "eco")
    assert snap(base, *paths) == first
    assert calls == []


def test_main_rejects_args():
    assert gm.main(["apply", "turbo"]) == 2
    assert gm.main(["apply"]) == 2
    assert gm.main(["rm", "-rf"]) == 2
    assert gm.main(["apply", "eco", "extra"]) == 2
    assert gm.main(["normalize", "x"]) == 2


def test_main_requires_root():
    if os.geteuid() == 0:
        return
    assert gm.main(["apply", "eco"]) == 1
    assert gm.main(["normalize"]) == 1


def test_created_dir_ignores_caller_umask():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    old = os.umask(0)
    try:
        run_apply(base, "eco")
    finally:
        os.umask(old)
    dropin_dir = Path(base, gm.DROPIN_PATH.lstrip("/")).parent
    assert dropin_dir.stat().st_mode & 0o777 == 0o755


def test_writable_parent_refused_before_write():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    dropin_dir = Path(base, gm.DROPIN_PATH.lstrip("/")).parent
    dropin_dir.mkdir(parents=True)
    dropin_dir.chmod(0o777)
    paths = ("etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value",
             gm.HOOK_PATH, gm.DROPIN_PATH)
    before = snap(base, *paths)
    written = []
    original = gm._atomic_write

    def spy(path, data, mode):
        written.append(str(path))
        return original(path, data, mode)

    gm._atomic_write = spy
    try:
        assert raises_apply(lambda: run_apply(base, "eco"))
    finally:
        gm._atomic_write = original
    assert not any(p.endswith("delay-start.conf") for p in written), written
    assert snap(base, *paths) == before


def test_foreign_owned_parent_refused():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    assert raises_apply(lambda: apply(base, "eco", owner_uid=os.getuid() + 1))
    assert not Path(base, gm.DROPIN_PATH.lstrip("/")).exists()


def test_normalize_refused_under_pkexec():
    os.environ["PKEXEC_UID"] = "1000"
    try:
        assert gm.main(["normalize"]) == 2
    finally:
        del os.environ["PKEXEC_UID"]


def marker(base):
    return Path(base, gm.PENDING_MARKER.lstrip("/"))


def fail_conf_write_once(fn):
    original = gm._atomic_write
    state = {"failed": False}

    def failing(path, data, mode):
        if str(path).endswith("supergfxd.conf") and not state["failed"]:
            state["failed"] = True
            raise OSError("disk full")
        return original(path, data, mode)

    gm._atomic_write = failing
    try:
        assert raises_apply(fn)
    finally:
        gm._atomic_write = original
    assert state["failed"]


def test_marker_records_boot_mode_and_clears():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    apply(base, "ultimate", runtime=lambda: "Hybrid")
    assert marker(base).read_text() == "standard\n"
    assert marker(base).stat().st_mode & 0o777 == 0o644
    assert marker(base).parent.stat().st_mode & 0o777 == 0o755
    apply(base, "eco", runtime=lambda: "AsusMuxDgpu")
    assert marker(base).read_text() == "standard\n"
    apply(base, "standard", runtime=lambda: "AsusMuxDgpu")
    assert not marker(base).exists()


def test_revert_without_supergfxd():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    apply(base, "ultimate")
    assert mux_file(base).read_text() == "0"
    got = gm.state(gm.Root(base), None, Path("/x"))
    assert got["active"] == "standard" and got["pendingMode"] == "ultimate", got
    assert got["inconsistent"] is True
    apply(base, got["active"])
    assert not marker(base).exists()
    assert mux_file(base).read_text() == "1"
    assert json.loads(conf_file(base).read_text())["mode"] == "Hybrid"


def test_marker_falls_back_to_runtime():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    marker(base).parent.mkdir(parents=True)
    marker(base).write_text("garbage\n")
    apply(base, "eco", runtime=lambda: "AsusMuxDgpu")
    assert marker(base).read_text() == "ultimate\n"


def test_marker_rolled_back():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    fail_conf_write_once(lambda: apply(base, "eco", runtime=lambda: "Hybrid"))
    assert not marker(base).exists()
    put(base, gm.PENDING_MARKER, "standard\n", 0o644)
    fail_conf_write_once(lambda: apply(base, "standard", runtime=lambda: "AsusMuxDgpu"))
    assert marker(base).read_text() == "standard\n"


def test_normalize():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="1")
    assert gm.normalize(gm.Root(base)) is True
    assert json.loads(conf_file(base).read_text()) == {"mode": "Hybrid", "hotplug_type": "Asus"}
    assert conf_file(base).stat().st_mode & 0o777 == 0o644
    for conf_mode, mux in (("AsusMuxDgpu", "0"), ("Hybrid", "1"), ("Integrated", "1")):
        base = fakeroot.build(conf_mode=conf_mode, mux=mux)
        conf_file(base).write_text(json.dumps({"mode": conf_mode, "hotplug_type": "None",
                                               "vfio_enable": True, "keep": [1]}))
        assert gm.normalize(gm.Root(base)) is True
        assert json.loads(conf_file(base).read_text()) == {
            "mode": conf_mode, "hotplug_type": "Asus", "vfio_enable": True, "keep": [1]}
        before = conf_file(base).read_bytes()
        assert gm.normalize(gm.Root(base)) is False
        assert conf_file(base).read_bytes() == before


def test_normalize_refuses_bad_conf():
    base = fakeroot.build(conf_text="{not json")
    put(base, gm.HOOK_PATH, "old hook", 0o755)
    assert raises_apply(lambda: gm.normalize(gm.Root(base)))
    assert conf_file(base).read_text() == "{not json"


def test_normalize_removes_old_hook():
    for conf_mode in ("Hybrid", "Integrated", "AsusMuxDgpu"):
        base = fakeroot.build(conf_mode=conf_mode, mux="1")
        put(base, gm.HOOK_PATH, "old hook", 0o755)
        gm.normalize(gm.Root(base))
        assert not old_hook(base).exists(), conf_mode


def test_normalize_removes_stock_hook_in_eco_only():
    base = fakeroot.build(conf_mode="Integrated", mux="1")
    put(base, gm.STOCK_HOOK_PATH, "stock", 0o755)
    gm.normalize(gm.Root(base))
    assert not Path(base, gm.STOCK_HOOK_PATH.lstrip("/")).exists()
    for conf_mode in ("Hybrid", "AsusMuxDgpu"):
        base = fakeroot.build(conf_mode=conf_mode, mux="1")
        put(base, gm.STOCK_HOOK_PATH, "stock", 0o755)
        gm.normalize(gm.Root(base))
        assert Path(base, gm.STOCK_HOOK_PATH.lstrip("/")).read_text() == "stock"


def test_dropin_matches_stock():
    stock = Path("/usr/share/omarchy/default/systemd/system/supergfxd.service.d/delay-start.conf")
    if stock.is_file():
        assert gm.DROPIN_SOURCE == stock.read_text()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
