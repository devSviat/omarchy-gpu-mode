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


def conf_file(base):
    return Path(base) / "etc/supergfxd.conf"


def put(base, rel, text, mode):
    p = fakeroot.write(base, rel.lstrip("/"), text)
    p.chmod(mode)
    return p


def eco_files(base):
    return {rel: Path(base, rel.lstrip("/")) for rel in
            (gm.HOOK_PATH, gm.DROPIN_PATH)}


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
    assert gm.target_config(conf, "standard") == {"mode": "Hybrid", "hotplug_type": "None", "x": [1]}
    eco = gm.target_config(conf, "eco")
    assert eco == {"mode": "Integrated", "vfio_enable": True, "hotplug_type": "None", "x": [1]}
    assert conf["mode"] == "Hybrid" and "vfio_enable" not in conf
    assert gm.target_config(conf, "ultimate")["mode"] == "AsusMuxDgpu"


def test_standard_to_eco():
    base = fakeroot.build(conf_mode="Hybrid", mux="1")
    conf_file(base).write_text(json.dumps({"mode": "Hybrid", "hotplug_type": "None", "keep": 7}))
    put(base, gm.STOCK_HOOK_PATH, "#!/bin/bash\n", 0o755)
    calls = run_apply(base, "eco")
    got = json.loads(conf_file(base).read_text())
    assert got == {"mode": "Integrated", "vfio_enable": True, "hotplug_type": "None", "keep": 7}
    assert mux_file(base).read_text() == "1\n"
    hook, dropin = Path(base, gm.HOOK_PATH.lstrip("/")), Path(base, gm.DROPIN_PATH.lstrip("/"))
    assert hook.read_text() == gm.HOOK_SOURCE and hook.stat().st_mode & 0o777 == 0o755
    assert dropin.read_text() == gm.DROPIN_SOURCE and dropin.stat().st_mode & 0o777 == 0o644
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
    for p in eco_files(base).values():
        assert not p.exists()
    assert calls == [1]


def test_ultimate_to_eco_single_step():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="0")
    run_apply(base, "eco")
    assert mux_file(base).read_text() == "1"
    assert json.loads(conf_file(base).read_text())["mode"] == "Integrated"
    for p in eco_files(base).values():
        assert p.is_file()


def test_ultimate_refused_when_dgpu_disabled():
    base = fakeroot.build(conf_mode="Hybrid", mux="1", dgpu_disable="1")
    before = snap(base, "etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value")
    assert raises_apply(lambda: run_apply(base, "ultimate"))
    after = snap(base, "etc/supergfxd.conf", fakeroot.ARMOURY + "/gpu_mux_mode/current_value")
    assert before == after


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
    original = gm._write_mux
    gm._write_mux = lambda path, value: writes.append(value)
    try:
        run_apply(base, "standard")
    finally:
        gm._write_mux = original
    assert writes == ["1"]


def test_rollback_restores_mux_even_when_readback_lies():
    base = fakeroot.build(conf_mode="AsusMuxDgpu", mux="0")
    original_write, lying = gm._write_mux, None
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

    gm._write_mux, gm._atomic_write = write, failing
    try:
        assert raises_apply(lambda: run_apply(base, "standard"))
    finally:
        gm._write_mux, gm._atomic_write = original_write, original_atomic
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
    original_write, original_atomic = gm._write_mux, gm._atomic_write
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

    gm._write_mux, gm._atomic_write = write, failing
    try:
        apply(base, "eco")
        raise AssertionError("no error")
    except gm.ApplyError as exc:
        msg = str(exc)
    finally:
        gm._write_mux, gm._atomic_write = original_write, original_atomic
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
    assert json.loads(conf_file(base).read_text())["mode"] == "Hybrid"
    for conf_mode, mux in (("AsusMuxDgpu", "0"), ("Hybrid", "1"), ("Integrated", "1")):
        base = fakeroot.build(conf_mode=conf_mode, mux=mux)
        before = conf_file(base).read_bytes()
        assert gm.normalize(gm.Root(base)) is False
        assert conf_file(base).read_bytes() == before


def test_normalize_removes_stock_hook_when_ours_present():
    base = fakeroot.build(conf_mode="Integrated", mux="1")
    put(base, gm.HOOK_PATH, gm.HOOK_SOURCE, 0o755)
    put(base, gm.STOCK_HOOK_PATH, "stock", 0o755)
    gm.normalize(gm.Root(base))
    assert not Path(base, gm.STOCK_HOOK_PATH.lstrip("/")).exists()
    assert Path(base, gm.HOOK_PATH.lstrip("/")).is_file()


def test_normalize_keeps_stock_hook_when_ours_absent():
    base = fakeroot.build(conf_mode="Integrated", mux="1")
    put(base, gm.STOCK_HOOK_PATH, "stock", 0o755)
    gm.normalize(gm.Root(base))
    assert Path(base, gm.STOCK_HOOK_PATH.lstrip("/")).read_text() == "stock"


def test_hook_parses():
    path = Path(fakeroot.mkdtemp("gpumode-hook-")) / "hook"
    path.write_text(gm.HOOK_SOURCE)
    done = subprocess.run(["/usr/bin/bash", "-n", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert gm.HOOK_SOURCE.startswith("#!/bin/bash\n")
    assert "/run/omarchy-gpu-mode-igpu" in gm.HOOK_SOURCE
    assert "force-igpu, MIT" in gm.HOOK_SOURCE


def test_dropin_matches_stock():
    stock = Path("/usr/share/omarchy/default/systemd/system/supergfxd.service.d/delay-start.conf")
    if stock.is_file():
        assert gm.DROPIN_SOURCE == stock.read_text()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
