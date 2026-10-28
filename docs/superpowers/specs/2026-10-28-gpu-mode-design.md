# GPU Mode for Omarchy — Design

Date: 2026-10-28 · Author: devSviat · Status: approved 2026-10-28 · local only, not published

## Why

On Windows, G-Helper switches the ASUS graphics mode with one click: Eco (iGPU only), Standard (hybrid, the dGPU wakes on demand) or Ultimate (the MUX hands the panel to the dGPU). On Omarchy there is no equivalent. The stock `omarchy-toggle-hybrid-gpu` switches only Integrated ↔ Hybrid, in a terminal, and cannot reach Ultimate.

The user switches modes by hand, for one reason: **"I need to save battery now" → Eco; "I don't" → Standard or Ultimate.** This plugin does only that.

### Relation to other plugins

Several catalog plugins expose GPU modes as part of larger ASUS control centres. Examples: `io.github.moneytosms.asus`, `gdeyoung.armoury`, `io.github.siddid-soni.armoury`. This is an independent, single-purpose implementation. The author has not audited those projects and makes no claims about them. The reasons for a separate plugin:
- they bundle many unrelated features;
- this machine already relies on `supergfxd` as the only GPU-mode owner, and the plugin must cooperate with it.

## Goals

- A G-Helper-style window with three modes: **Eco / Standard / Ultimate**. It shows the current mode, a plain description of the selected one, and the consequences.
- **Every switch takes exactly one reboot, including Ultimate ↔ Eco.**
- **A switch is always applied with an immediate reboot.** There is no "apply later" and no long-lived pending state.
  - The user dropped "apply later" after review. A switch recorded for later can be silently overridden by another writer (for example the stock `omarchy-toggle-hybrid-gpu`), and then the older change wins over the newer one.
- A warning about external monitors, shown **only when a monitor is actually connected** to a port that Eco disables.
- Privileged steps go through the themed Omarchy polkit dialog. No terminal, no `sudo` prompt in a terminal.

## Non-goals

- An "Optimized" mode (automatic Eco on battery). On Linux each switch needs a reboot here, so automation makes no sense.
- Live Eco without a reboot or logout. Hyprland holds `/dev/dri/card1`, and the user chose reboot.
- Performance profiles, fans, lighting, charge limits, power limits.
- Fixing the dGPU staying awake in Standard. This is a separate follow-up task.
- Other laptops or vendors. Being generic is welcome where it costs nothing, but it is not a goal.

## Anti-goals (failure even if it "works")

- Any path that needs two reboots.
- A machine that boots to a black screen or hangs because of a half-applied switch.
- Two writers for the same state: the plugin and `supergfxd` both writing `/etc/supergfxd.conf`, or `asusd` and the plugin both driving the GPU attributes.
- A switch that is written but not followed by a reboot, leaving the config describing a mode that is not running.
- Turning the dGPU off live while Hyprland still holds it (see "Sleep hook").
- `pkexec` on a file the user can write.

## Context and facts (verified on this machine 2026-10-28)

### Hardware
- ASUS ROG Zephyrus G16 GU603ZV: Intel iGPU (`0000:00:02.0`, card2) and RTX 4060 Laptop (`0000:01:00.0`, `10DE:28E0`, card1).
- **The external outputs `HDMI-A-1` and `DP-1` (USB-C) are on card1, the NVIDIA card.** In Eco they do not work.
- The internal panel is `eDP-2` on card2 in Hybrid and `eDP-1` on card1 in Ultimate.
- MUX: `/sys/class/firmware-attributes/asus-armoury/attributes/gpu_mux_mode/current_value` (also `/sys/devices/platform/asus-nb-wmi/gpu_mux_mode`). `1` = Optimus (iGPU drives the panel), `0` = dGPU. The kernel exposes `pending_reboot`.
- `dgpu_disable` exists and is `0`. The kernel refuses to set MUX = dGPU while `dgpu_disable=1`.
- NVIDIA modules are in the initramfs: `/etc/mkinitcpio.conf.d/nvidia.conf` has `MODULES+=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)`.

### supergfxd 5.2.7 (read from source, tag `5.2.7`, gitlab.com/asus-linux/supergfxctl)
- It is installed, enabled and running. Supported modes: `Integrated, Hybrid, AsusMuxDgpu`. Members of `wheel` may call it over D-Bus without root.
- Config: `/etc/supergfxd.conf`, currently with `"hotplug_type": "None"`. It also currently says `"mode": "AsusMuxDgpu"` although the MUX is in Optimus. The boot safety check corrects the mode in memory only and never writes the file.
- **The config lives in memory.** supergfxd rewrites the whole file only after one of its own mode changes completes (`config.write()` in `controller.rs`). A hand edit is therefore safe as long as nothing calls `supergfxctl -m` before the reboot.
- Boot (`do_boot_tasks`): it reads the mode, then `asus_boot_safety_check`:
  - MUX = dGPU → the mode is forced to `AsusMuxDgpu`;
  - MUX = Optimus and mode `AsusMuxDgpu` → the mode is forced to `Hybrid`;
  - MUX = Optimus and mode `Integrated` → **accepted**.
  - Integrated boot actions: stop nvidia-powerd → `kill -9` whatever holds `/dev/nvidia0` → unload drivers → unbind and remove the PCI device → write the modprobe conf.
  - It is safe because the unit is `Type=dbus` and `Before=display-manager.service`: SDDM and Hyprland start after it.
- Switch semantics of `supergfxctl -m`:
  - from `AsusMuxDgpu` to anything: it only flips the MUX and saves the mode. **One reboot, Ultimate → Eco included.**
  - `Hybrid ↔ Integrated` through `-m`: waits for logout and **stops display-manager**. This is why the stock Omarchy toggle edits the config file and reboots instead.
- Kernel cmdline `supergfxd.mode=<Mode>` overrides the config at boot. It is the recovery hatch, set from the Limine menu.

### Omarchy 4.0.6
- Stock toggle: `/usr/bin/omarchy-toggle-hybrid-gpu`. For Integrated it:
  - `sed`-edits the config to `mode: Integrated` and `vfio_enable: true`;
  - installs the drop-in `/etc/systemd/system/supergfxd.service.d/delay-start.conf` (`ExecStartPre=/bin/sleep 5`, to avoid a boot freeze);
  - installs the sleep hook `/usr/lib/systemd/system-sleep/force-igpu`.
  - Going back to Hybrid removes both files. Migration `1788662350.sh` re-installs or repairs these files when they exist but look unsafe.
- `force-igpu` decides by **grepping the config for `Integrated`**. After resume it does `supergfxctl -m Vfio` then `-m Integrated`, and on hibernate it switches to Vfio first.
- Menu: the shell merges only `default/omarchy/omarchy-menu.jsonc` and `~/.config/omarchy/extensions/omarchy-menu.jsonc`. **Plugins cannot register menu rows.** The stock row is `trigger.hardware.hybrid-gpu`, with `when: omarchy-hw-hybrid-gpu`. Redefining an id in the user file **replaces the whole row**: `normalizeItem` fills every field, despite the file's comment saying fields are kept.
- Panels: a plugin of kind `panel` is opened with `omarchy-shell shell summon <id> <payloadJson>`. Reference: stock `plugins/panels/wifiqr`.
- Reboot: `omarchy-system-reboot` schedules the reboot in the user manager, shows an OSD and closes windows gracefully.
- Hyprland env: Omarchy applies NVIDIA env vars only when an NVIDIA PCI display device exists. The user's `~/.config/hypr/hyprland.lua` sets `LIBVA_DRIVER_NAME=iHD` when `gpu_mux_mode=1`, which covers Eco too.
- Plugin structure reference: the author's `sviat.nightlight` (`Service.qml` singleton, `Panel.qml`, `Model.js`, `bin/`, `install.sh`, `tests/`).

- In Integrated, supergfxd's modprobe conf contains only `blacklist nvidia*` lines, with no `install … /bin/false`. A blacklist stops alias autoloading but not an explicit `modprobe`. So an initramfs rebuilt while in Eco (kernel update) still loads the explicit `MODULES+=(nvidia …)`, and supergfxd rewrites the conf when it boots into another mode. The plugin does not touch the modprobe conf or the initramfs. The Eco→Ultimate-after-kernel-update case is tested on the hardware, with `supergfxd.mode=` as the recovery.

### Other machine-specific facts
- asusd 6.5 can also write `dgpu_disable` and `gpu_mux_mode` (it queues them until reboot as `QueuedGpuValue`), and `/etc/asusd/asusd.ron` stores nothing GPU-related. The plugin never uses asusd for GPU mode.
- Backlight: `backlight-mirror.service` copies `intel_backlight` (if present, else `nvidia_0`) to `nvidia_wmi_ec_backlight`. In Eco `nvidia_0` disappears; whether WMI EC still dims the panel is **untested**.

## Decisions taken with the user

- The backend is **supergfxd only**. Modes map as Eco = `Integrated`, Standard = `Hybrid`, Ultimate = `AsusMuxDgpu`.
- Eco and Ultimate are applied by **reboot**, never live.
- Every switch takes **one** reboot.
- The UI is **variant B**, a G-Helper-style window: three mode buttons with "current" marked, a description of the selection, an optional monitor warning, and buttons **Cancel / Apply and reboot**. "Apply later" was considered and dropped.
- Entry point: the Omarchy menu, **Trigger → Hardware → "GPU Mode"**, which **replaces** the stock "Hybrid GPU" row in place.
- An optional bar icon exists but is **off by default**.
- The monitor warning appears only if something is connected to a port Eco disables.
- Privileged actions go through polkit, using the themed Omarchy agent.
- The dGPU-awake-in-Standard problem is a separate later task.

## Architecture

```
Omarchy menu row ──summon──▶ Panel.qml (window, variant B)
                                 │ reads state via Service.qml / Model.js (no root)
                                 │ on confirm: pkexec <root helper> <mode>
                                 ▼
                       root helper (root-owned, fixed path, polkit action)
                       writes MUX + /etc/supergfxd.conf + Eco boot/sleep files
                                 │ success
                                 ▼
                       omarchy-system-reboot (run as the user, immediately)
```

### State the UI reads (all without root)
- **Active mode:** `supergfxctl -g` first (`Integrated` → Eco, `Hybrid` → Standard, `AsusMuxDgpu` → Ultimate), because it reports the mode the machine booted with while the MUX value may already show a written switch. Only when it fails or reports something else does the derivation fall back to the MUX: `0` → Ultimate; `1` → Eco if no NVIDIA device is visible, else Standard.
- **MUX:** the current value. The existing config can be stale (`AsusMuxDgpu` while the MUX is Optimus), which counts as Standard unless a switch is pending. The installer normalises that config once.
- **Inconsistent state:** the root-owned marker `/run/omarchy-gpu-mode/pending` exists, or the configured mode disagrees with what is active. The helper writes the marker (the mode the current boot started in) on every switch away from that mode and removes it on a switch back; `/run` is cleared by the reboot. The kernel's `pending_reboot` is still reported but does not drive this state. It happens only if a reboot after a switch did not take place, or someone edited the config by hand. The window then shows "A GPU switch is waiting for a reboot" with **Reboot now** and **Revert**; Revert is the helper called with the active mode. This is a recovery path, not a feature. Whether `current_value` shows a newly written MUX before the reboot is checked on the hardware.
- **Monitor warning:** shown when the target is Eco and any non-eDP connector of the NVIDIA DRM card (found by PCI vendor `0x10de`, not by card number) has `status = connected`.

### Root helper
- One small script, installed root-owned at a fixed system path (for example `/usr/local/libexec/omarchy-gpu-mode/apply`). A polkit action names it with `org.freedesktop.policykit.exec.path` and carries a readable message ("Switch GPU mode"). The default is `auth_admin`.
- It accepts exactly `<eco|standard|ultimate>` and rejects everything else. It reads no environment it does not need. It ships with its own copies of the files it installs; it does not read them from the user-writable plugin directory.
- Steps, all idempotent:
  1. Compute the target config: `mode`, plus `vfio_enable: true` for Eco, matching the stock toggle.
  2. If the target MUX differs from the current one, write `gpu_mux_mode`. Refuse to set MUX = dGPU while `dgpu_disable=1`.
  3. Install the Eco-only boot and sleep files for Eco, and remove them for the other modes (see "Sleep hook").
  4. Write `/etc/supergfxd.conf` atomically (temp file in the same directory, then rename), preserving all other keys.
  5. Never call `supergfxctl -m`, so supergfxd cannot overwrite the file before the reboot.
- On any failure it restores the previous config and MUX, and exits non-zero with a message the window can show.
- The writes happen at switch time, the same as the stock toggle. The helper never reboots: the window runs `omarchy-system-reboot` as the user right after the helper succeeds. If the reboot cannot be scheduled, the window calls the helper with the active mode to revert, and shows the error.
- Author's call, replacing the builder-check idea of a boot-time apply unit: without "apply later", the gap between the write and the reboot is seconds, so the extra unit and the pending file are not worth their complexity. The residual risk is a supergfxd crash-restart inside those seconds, which would run the new mode's boot actions live. It is accepted.

### Sleep hook
- The stock `force-igpu` hook keys off the config. The plugin uses its own sleep hook with the same Vfio→Integrated logic, plus a guard: act only when the **active** mode is `Integrated` and the config agrees. The plugin removes the stock `force-igpu` when it installs its own, so there is exactly one hook; the window shows a notice if the stock one reappears (for example via a migration).
- Whether the G16 needs this hook at all (the G14 wakes in Hybrid after suspend) is unknown; finding out is part of hardware testing.
- Stock `omarchy-toggle-hybrid-gpu` stays callable from the CLI and is not guarded against. The menu row no longer reaches it, running it by hand is a deliberate choice, and with immediate reboots there is no pending state for it to conflict with.
- The `delay-start.conf` drop-in is installed for Eco and removed otherwise.

### Panel (variant B)
- A `panel` plugin opened by `omarchy-shell shell summon sviat.gpu-mode '{}'`.
- Layout: title "GPU Mode" and "Now: Standard". Three buttons Eco / Standard / Ultimate; the active one is tagged "current" and not selectable as a switch.
- Below the buttons: a description of the selected mode, the monitor warning (conditional), and an error line when the helper fails.
- Buttons: **Cancel**, **Apply and reboot**.
- The inconsistent-state banner (see "State the UI reads") replaces the buttons when it applies.
- Keyboard: arrows select, Enter applies-and-reboots, Esc closes. The theme follows Omarchy tokens, like the other panels.
- Mode descriptions:
  - Eco: the dGPU is fully off, best battery life, games and CUDA cannot see the dGPU.
  - Standard: the iGPU drives the screen and the dGPU wakes on demand.
  - Ultimate: the dGPU drives the screen directly, best performance, highest power draw.
- While the helper runs, the buttons are disabled. Cancelling the polkit dialog changes nothing and returns to the window silently.

### Menu integration
- Plugins cannot add menu rows, so `bin/` ships an installer/remover for `~/.config/omarchy/extensions/omarchy-menu.jsonc`, following `ReidenXerx/omarchy-dgpu-status`'s `dgpu-status-menu-install`.
- The stock gate `when: omarchy-hw-hybrid-gpu` (checks that `supergfxctl -s` lists Hybrid) is kept. In 5.2.7 `get_supported_modes` always starts with `[Integrated, Hybrid]`; it returns `[Integrated]` only when the dGPU vendor is unknown **and** `dgpu_disable` is absent, and `dgpu_disable` exists here. So the row stays visible in Eco and Ultimate. Confirm on the hardware.
- It writes a marked block that redefines `trigger.hardware.hybrid-gpu` in full: icon, label "GPU Mode", `when: omarchy-hw-hybrid-gpu`, and an action that summons the panel.
- It preserves the rest of the file, comments included, and backs up before writing. Remove restores the stock row.

### Optional bar widget
- Off by default; the user enables it in Omarchy's plugin settings.
- It shows the active-mode icon, and a warning marker in the inconsistent state. A click opens the same panel.

## Installation

- **Local only until it is tested on the hardware.** No GitHub remote, no push, no catalog submission. Publishing is a separate later decision.
- Author's call, so that publishing later costs nothing: UI strings, code comments and the README are in English, and nothing personal is hard-coded. Machine facts (the NVIDIA card, MUX path, eDP name) are detected at runtime, not written as constants.

- Plugin files: `~/.config/omarchy/plugins/sviat.gpu-mode`, as a link to `~/Projects/omarchy-gpu-mode`, the same setup as nightlight.
- One-time root install: the helper, the polkit action, the sleep hook template and the drop-in template. There is no passwordless sudo on this machine, so the user runs this step from a printed command.
- The root install also normalises the current stale `/etc/supergfxd.conf` mode to match the MUX.
- The menu row is added by the user-level installer.
- Uninstall reverses both and restores the stock menu row.

## Testing

- Unit tests (Model.js / helper): the mode↔config↔MUX mapping, the active/inconsistent derivation (including the stale-config case), argument validation, config rewriting that preserves unknown keys, and monitor detection from a fake sysfs tree.
- Hardware matrix on the G16, each run checked after the reboot with `supergfxctl -g`, `gpu_mux_mode` and the dGPU PCI presence:
  - all 6 transitions;
  - Eco: brightness on AC and on battery, suspend and resume;
  - the inconsistent-state banner (simulate a switch without a reboot), and Revert from it;
  - the monitor warning with HDMI connected and disconnected;
  - polkit cancel; helper failure (a simulated write error) leaves the old state intact.
- **Standard mode acceptance.** This checks Standard behaviour, not just that the switch landed. Fixing what fails is the follow-up task; the results feed it.
  - The desktop renders on Intel: the panel is `eDP-2` on card2, and `LIBVA_DRIVER_NAME=iHD`.
  - Offload works: `prime-run` (nvidia-prime 1.0 is installed) runs `vkcube`/`glxinfo -B` on the RTX 4060, and a Steam game picks the dGPU.
  - External monitors work on HDMI-A-1 and USB-C DP-1.
  - Browser hardware video decode works (iHD) with a picture.
  - The dGPU sleeps when idle. The driver reports `Runtime D3 status: Enabled (fine-grained)` and power control is `auto`, yet on 2026-10-28 `runtime_status` stayed `active`: Hyprland, Xwayland, zed-editor and voxtype-osd held `/dev/dri/card1`, `renderD128` or `/dev/nvidia*`. Record the holders and `runtime_status` on AC and on battery, with and without an external monitor. This is the expected failure and the input for the follow-up.
  - nvidia-powerd: asusd stops it on battery (`disable_nvidia_powerd_on_battery: true`). Note its state on AC.
- Recovery documented in the README: add `supergfxd.mode=Hybrid` to the kernel cmdline from the Limine menu.

## Left to the builder

- File and module layout within the nightlight pattern; icons; exact UI copy (wording, not meaning).
- The helper language (bash or something else), provided it meets the helper rules above.
- How the sleep hook detects "active Integrated", provided it never acts on the config alone.
- The polkit action id, message text and install paths.
