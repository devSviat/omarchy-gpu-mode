import importlib.machinery
import importlib.util
import json
import atexit
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARMOURY = "sys/class/firmware-attributes/asus-armoury/attributes"


_dirs = []
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in _dirs])


def mkdtemp(prefix):
    path = tempfile.mkdtemp(prefix=prefix)
    _dirs.append(path)
    return path


def load_module():
    path = str(REPO / "libexec" / "gpu-mode")
    loader = importlib.machinery.SourceFileLoader("gpumode", path)
    spec = importlib.util.spec_from_loader("gpumode", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write(base, rel, text):
    path = Path(base) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def build(conf_mode="Hybrid", mux="1", dgpu_disable="0", pending="0", nvidia=True,
          connectors=None, conf_text=None):
    base = mkdtemp("gpumode-root-")
    if conf_text is None:
        conf_text = json.dumps({"mode": conf_mode})
    write(base, "etc/supergfxd.conf", conf_text)
    if mux is not None:
        write(base, f"{ARMOURY}/gpu_mux_mode/current_value", mux + "\n")
    write(base, f"{ARMOURY}/dgpu_disable/current_value", dgpu_disable + "\n")
    write(base, f"{ARMOURY}/pending_reboot", pending + "\n")
    write(base, "sys/bus/pci/devices/0000:00:02.0/vendor", "0x8086\n")
    write(base, "sys/bus/pci/devices/0000:00:02.0/class", "0x030000\n")
    (Path(base) / "sys/bus/pci/devices/0000:00:02.0/drm/card0").mkdir(parents=True)
    if nvidia:
        write(base, "sys/bus/pci/devices/0000:01:00.0/vendor", "0x10de\n")
        write(base, "sys/bus/pci/devices/0000:01:00.0/class", "0x030200\n")
        (Path(base) / "sys/bus/pci/devices/0000:01:00.0/drm/card1").mkdir(parents=True)
        write(base, "sys/bus/pci/devices/0000:01:00.1/vendor", "0x10de\n")
        write(base, "sys/bus/pci/devices/0000:01:00.1/class", "0x040300\n")
    for name, status in (connectors or {}).items():
        write(base, f"sys/class/drm/{name}/status", status + "\n")
    return base
