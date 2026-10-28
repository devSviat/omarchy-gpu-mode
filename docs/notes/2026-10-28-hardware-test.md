# Hardware test — 2026-10-28

Machine: ASUS ROG Zephyrus G16 GU603ZV (Intel iGPU + RTX 4060 Laptop), Omarchy 4.0.6,
kernel 7.2.8-9-omarchy, supergfxctl 5.2.7, nvidia-open 615.78.08.

Each step was checked after the reboot with `gpu-mode state`, `dgpu_disable`/`gpu_mux_mode`
`current_value`, and the presence of PCI device `0000:01:00.0`.

## Transitions (all through the GPU Mode window)

| Transition | Reboots | Result |
|---|---|---|
| Standard → Eco | 1 | eco, MUX 1, dgpu_disable 1, dGPU removed |
| Eco → Standard | 1 | standard, MUX 1, dgpu_disable 0, dGPU present |
| Standard → Ultimate | 1 | ultimate, MUX 0, dgpu_disable 0 |
| Ultimate → Eco | 1 | eco, MUX 1, dgpu_disable 1, dGPU removed |
| Eco → Ultimate | 1 | ultimate, MUX 0, dgpu_disable 0 (kernel accepted MUX right after dgpu_disable=0) |
| Ultimate → Standard | 1 | standard, MUX 1, dgpu_disable 0 |

## Other checks

- Revert before reboot: `apply ultimate` then `apply standard` without rebooting booted into
  Standard. The MUX write-back cancels the latched switch.
- Firmware readback: `gpu_mux_mode/current_value` keeps showing the boot value after a write,
  and `pending_reboot` stays 1 even after writing the old value back. The helper therefore
  never decides by readback, and the pending state comes from `/run/omarchy-gpu-mode/pending`.
- Eco suspend (`rtcwake -m no -s 60 && systemctl suspend`): the dGPU did not reappear on
  resume; supergfxd's wake handler logged `already set to true. Early return`.
- Eco brightness works on AC and battery; Ultimate brightness works.
- Standard: `prime-run vkcube` renders on the RTX 4060. The dGPU stays `active` because
  Hyprland, Xwayland and voxtype-osd hold it (the external ports are wired to it). This is known
  upstream behaviour; accepted, use Eco on battery.
- Menu row: hidden in Ultimate with Omarchy's `omarchy-hw-hybrid-gpu` gate, because
  `supergfxctl -s` lists only `[AsusMuxDgpu]` there. Fixed with the row's own gate; the window
  then opened from the menu in Ultimate.

## Failed first design (kept for the record)

Eco through `hotplug_type: None` plus Omarchy's force-igpu sleep hook did not hold: on resume
the firmware re-added the dGPU, the nvidia module (probed every ~2 s by something in the
session) bound to it, and Hyprland hot-plugged the card within 2 s. Replaced by the
firmware power-off (`hotplug_type: Asus`, `dgpu_disable`).
