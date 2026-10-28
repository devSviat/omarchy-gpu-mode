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
- Turning the dGPU off live while Hyprland still holds it (see "Eco power-off").
- `pkexec` on a file the user can write.

## Context and facts (verified on this machine 2026-10-28)

### Hardware
- ASUS ROG Zephyrus G16 GU603ZV: Intel iGPU (`0000:00:02.0`, card2) and RTX 4060 Laptop (`0000:01:00.0`, `10DE:28E0`, card1).
- **The external outputs `HDMI-A-1` and `DP-1` (USB-C) are on card1, the NVIDIA card.** In Eco they do not work.
- The internal panel is `eDP-2` on card2 in Hybrid and `eDP-1` on card1 in Ultimate.
- MUX: `/sys/class/firmware-attributes/asus-armoury/attributes/gpu_mux_mode/current_value` (also `/sys/devices/platform/asus-nb-wmi/gpu_mux_mode`). `1` = Optimus (iGPU drives the panel), `0` = dGPU. The kernel exposes `pending_reboot`.
- `dgpu_disable` exists (`asus-armoury/attributes/dgpu_disable/current_value`, also `/sys/devices/platform/asus-nb-wmi/dgpu_disable`). The kernel refuses to set MUX = dGPU while `dgpu_disable=1`.
- `gpu_mux_mode/current_value` keeps reading the boot value after a write; `pending_reboot` stays `1` even after the old value is written back; writing the old value back before the reboot does cancel the switch.
- In Eco with `hotplug_type: None` the firmware re-adds the NVIDIA GPU to the PCI bus on resume. The `nvidia` module is then loaded by something polling about every 2 s, and Hyprland hot-plugs the new DRM card within about 2 s. `rtcwake -m mem` bypasses systemd-sleep, so sleep hooks do not run in that test.
- NVIDIA modules are in the initramfs: `/etc/mkinitcpio.conf.d/nvidia.conf` has `MODULES+=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)`.

### supergfxd 5.2.7 (read from source, tag `5.2.7`, gitlab.com/asus-linux/supergfxctl)
- It is installed, enabled and running. Supported modes: `Integrated, Hybrid, AsusMuxDgpu`. Members of `wheel` may call it over D-Bus without root.
- Config: `/etc/supergfxd.conf`, originally with `"hotplug_type": "None"`. It also currently says `"mode": "AsusMuxDgpu"` although the MUX is in Optimus. The boot safety check corrects the mode in memory only and never writes the file.
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
- `hotplug_type: "Asus"`: the Integrated boot actions end with `AsusDgpuDisable` (`dgpu_disable=1` after unbinding and removing the GPU). A Hybrid boot runs `AsusDgpuEnable` (`dgpu_disable=0`, PCI rescan) before loading drivers, but it only gets that far when `dgpu_disable` was already 0: while it is 1, the boot safety check below forces Integrated first. On wake from suspend (logind `PrepareForSleep` false) in Integrated it writes `dgpu_disable=1` again; the write is skipped when the value is already set.
- The boot safety check with `hotplug_type: "Asus"`: MUX = dGPU and `dgpu_disable=1` → it clears `dgpu_disable` itself and uses `AsusMuxDgpu`; `dgpu_disable=1` and mode not `Integrated` → it **forces Integrated**. So leaving Eco must clear `dgpu_disable` before the reboot, or Standard silently boots as Eco.
- Kernel cmdline `supergfxd.mode=<Mode>` overrides the config at boot, but it is no recovery hatch here: supergfxd persists it into the config (`reload()` writes it), with `"Asus"` and `dgpu_disable=1` the safety check still forces Integrated, and with MUX = dGPU any mode becomes `AsusMuxDgpu`. Recovery is from a TTY (see the README's "Recovery" and "Testing" below).

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

- In Integrated, supergfxd's modprobe conf contains only `blacklist nvidia*` lines, with no `install … /bin/false`. A blacklist stops alias autoloading but not an explicit `modprobe`. So an initramfs rebuilt while in Eco (kernel update) still loads the explicit `MODULES+=(nvidia …)`, and supergfxd rewrites the conf when it boots into another mode. The plugin does not touch the modprobe conf or the initramfs. The Eco→Ultimate-after-kernel-update case is tested on the hardware, with the TTY steps in "Recovery" as the fallback.

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
- 2026-10-28, after hardware testing: **Eco powers the dGPU off in firmware**, as G-Helper does, through supergfxd's `hotplug_type: "Asus"`. The plugin's own sleep hook is dropped. A pending switch is shown only from the plugin's marker, so a MUX flipped in the BIOS raises no banner. Revert uses the marker's boot mode when supergfxd is unreachable.

## Architecture

```
Omarchy menu row ──summon──▶ Panel.qml (window, variant B)
                                 │ reads state via Service.qml / Model.js (no root)
                                 │ on confirm: pkexec <root helper> <mode>
                                 ▼
                       root helper (root-owned, fixed path, polkit action)
                       writes dgpu_disable + MUX + /etc/supergfxd.conf + Eco drop-in
                                 │ success
                                 ▼
                       omarchy-system-reboot (run as the user, immediately)
```

### State the UI reads (all without root)
- **Active mode:** `supergfxctl -g` first (`Integrated` → Eco, `Hybrid` → Standard, `AsusMuxDgpu` → Ultimate), because it reports the mode the machine booted with while the MUX value may already show a written switch. When it fails or reports something else and a valid pending marker exists, the marker's boot mode is active, so Revert still targets the running mode. Otherwise the derivation falls back to the MUX: `0` → Ultimate; `1` → Eco if `dgpu_disable=1` or no NVIDIA device is visible, else Standard.
- **Configured mode:** reported as information only. A MUX flipped in the BIOS makes supergfxd adapt at boot without writing the config, so a config that disagrees with the active mode is not a pending switch.
- **Inconsistent state:** the root-owned marker `/run/omarchy-gpu-mode/pending` exists; nothing else. The helper writes the marker (the mode the current boot started in) on every switch away from that mode and removes it on a switch back; `/run` is cleared by the reboot. The kernel's `pending_reboot` is still reported but does not drive this state. It happens only if a reboot after a switch did not take place, or someone edited the config by hand. The window then shows "A GPU switch is waiting for a reboot" with **Reboot now** and **Revert**; Revert is the helper called with the active mode. This is a recovery path, not a feature. Whether `current_value` shows a newly written MUX before the reboot is checked on the hardware.
- **Kept-in-Eco notice:** active Eco, configured Standard or Ultimate, `dgpu_disable=1` and no marker means supergfxd's boot check forced Integrated after a switch; a BIOS MUX flip cannot produce it. The window says "supergfxd kept Eco because the NVIDIA GPU is still disabled in firmware. Apply <Label> again."
- **Pending banner:** ends with "Reboot before suspending.", because supergfxd re-disables the dGPU on resume while it still runs Eco.
- **Stock hook notice:** shown when Omarchy's `force-igpu` exists and the active mode is Eco: it would run its Vfio switch against the firmware-disabled dGPU.
- **Monitor warning:** shown when the target is Eco and any non-eDP connector of the NVIDIA DRM card (found by PCI vendor `0x10de`, not by card number) has `status = connected`.

### Root helper
- One small script, installed root-owned at a fixed system path (for example `/usr/local/libexec/omarchy-gpu-mode/apply`). A polkit action names it with `org.freedesktop.policykit.exec.path` and carries a readable message ("Switch GPU mode"). The default is `auth_admin`.
- It accepts exactly these argument lists and rejects everything else:
  - `state`: read-only, runs as the user without privileges;
  - `apply <eco|standard|ultimate>`: root, the only command reachable through the polkit action;
  - `normalize` and `restore-hotplug`: root, for the sudo install and remove steps only; both refuse when `PKEXEC_UID` is set.
- It reads no environment except that `PKEXEC_UID` refusal. It ships with its own copies of the files it installs; it does not read them from the user-writable plugin directory.
- Steps, all idempotent:
  1. Compute the target config: `mode`, and `hotplug_type: "Asus"` for every mode. `vfio_enable` is left as it is.
  2. When leaving Eco (target not Eco and `dgpu_disable=1`), record it in `/run/omarchy-gpu-mode/dgpu-cleared`, then write `dgpu_disable=0`, armoury attribute first, WMI path as the fallback. No PCI rescan; the reboot follows. This comes before the MUX write because the kernel refuses MUX = dGPU while `dgpu_disable=1`.
  3. If the target MUX differs from the current one, or `pending_reboot` is set, write `gpu_mux_mode`.
  4. On a revert to Eco in the boot that cleared `dgpu_disable` (the record exists), write `dgpu_disable=1` back after the MUX and drop the record, but only when no NVIDIA PCI function is present. Otherwise keep the pending marker, so the window still asks for a reboot; left at 0, supergfxd would write 1 on the next resume under a possibly bound driver.
  5. Remove the old plugin sleep hook if present. Install the Eco drop-in and remove the stock `force-igpu` for Eco; remove the drop-in for the other modes (see "Eco power-off").
  6. Write `/etc/supergfxd.conf` atomically (temp file in the same directory, then rename), preserving all other keys.
  7. Never call `supergfxctl -m`, so supergfxd cannot overwrite the file before the reboot.
- **Safety rule:** root never writes `dgpu_disable=1` while any NVIDIA PCI function (vendor `0x10de`) is present; writing it hot-removes the GPU. A switch to Eco from Standard or Ultimate never writes it: supergfxd does at the Eco boot.
- On any failure it restores the previous config, the `/run` files, and the attributes in reverse write order, and exits non-zero with a message the window can show. Restores are decided by what was written, never by readback, because the attributes keep reading the boot value. Restoring `dgpu_disable=1` follows the safety rule: with an NVIDIA function present it stays 0 and the message says "the NVIDIA GPU stays enabled until the next Eco boot".
- `normalize` (root install only, refused under `PKEXEC_UID`) sets `hotplug_type: "Asus"` in the existing config, corrects a stale `AsusMuxDgpu` with MUX = Optimus to `Hybrid`, then removes the old plugin sleep hook, and removes the stock `force-igpu` when the config is `Integrated`.
- `restore-hotplug` (root only, refused under `PKEXEC_UID` and in Eco) sets `hotplug_type: "None"`, keeping the other keys and the file mode. `install-root.sh --remove` runs it before removing the helper.
- The writes happen at switch time, the same as the stock toggle. The helper never reboots: the window runs `omarchy-system-reboot` as the user right after the helper succeeds. If the reboot cannot be scheduled, the window calls the helper with the active mode to revert, and shows the error.
- Author's call, replacing the builder-check idea of a boot-time apply unit: without "apply later", the gap between the write and the reboot is seconds, so the extra unit and the pending file are not worth their complexity. The residual risk is a supergfxd crash-restart inside those seconds, which would run the new mode's boot actions live. It is accepted.

### Eco power-off
- Eco relies on the firmware: with `hotplug_type: "Asus"`, supergfxd writes `dgpu_disable=1` at the Integrated boot, after unbinding and removing the GPU, and its wake handler writes it again after each resume. The firmware is expected to keep the GPU off the PCI bus across suspend; this is still to be verified on the hardware.
- The earlier design used a sleep hook adapted from Omarchy's `force-igpu` (Vfio→Integrated after resume). It was dropped on 2026-10-28: on resume the firmware re-adds the GPU, the `nvidia` module loads and Hyprland opens the new DRM card within about 2 s, so the hook cannot unload a driver Hyprland holds, and supergfxd's `kill -9` of `/dev/nvidia0` holders is unreliable and dangerous here.
- The helper and `normalize` remove the old hook file `/usr/lib/systemd/system-sleep/omarchy-gpu-mode-igpu` left by the earlier version.
- The stock `force-igpu` is removed on a switch to Eco, and the window shows a notice if it reappears in Eco (for example via a migration).
- Stock `omarchy-toggle-hybrid-gpu` stays callable from the CLI and is not guarded against. The menu row no longer reaches it, running it by hand is a deliberate choice, and with immediate reboots there is no pending state for it to conflict with. It cannot leave Eco while `hotplug_type` is `"Asus"`: it does not clear `dgpu_disable`, so the boot safety check forces Integrated again. GPU Mode's uninstall resets `hotplug_type` to `"None"` for that reason.
- The `delay-start.conf` drop-in, which Omarchy installs to avoid an Integrated boot race, is installed for Eco and removed otherwise.
- Removal (`install-root.sh --remove`, `install.sh --remove`) refuses while the config is in Eco, since the dGPU stays disabled in firmware.

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
- One-time root install: the helper and the polkit action; the helper carries the drop-in template. There is no passwordless sudo on this machine, so the user runs this step from a printed command.
- The root install also normalises `/etc/supergfxd.conf`: `hotplug_type: "Asus"` and a stale mode corrected to match the MUX.
- The menu row is added by the user-level installer.
- The root install ends with "Reboot to finish (Eco uses the new firmware power-off from the next boot)."
- Uninstall reverses both, resets `hotplug_type` to `"None"`, and restores the stock menu row.

## Testing

- Unit tests (Model.js / helper): the mode↔config↔MUX mapping, the active/inconsistent derivation (a BIOS MUX flip with no marker is consistent; the marker names the active mode when supergfxd is unreachable), `dgpu_disable` written to 0 before the MUX when leaving Eco, and to 1 only on a revert to Eco in the boot that cleared it and only when no NVIDIA function is present, its rollback, removal of the old hook, `normalize` setting `hotplug_type`, the revert-to-Eco re-disable with and without an NVIDIA function, the safety rule in rollback, the kept-in-Eco notice, `restore-hotplug` and the removal on a fake root, argument validation, config rewriting that preserves unknown keys, and monitor detection from a fake sysfs tree.
- Hardware matrix on the G16, each run checked after the reboot with `supergfxctl -g`, `gpu_mux_mode` and the dGPU PCI presence:
  - all 6 transitions;
  - Eco: brightness on AC and on battery; suspend and resume with `sudo rtcwake -m no -s 60 && systemctl suspend` (`rtcwake -m mem` bypasses logind and with it supergfxd's wake handler), checking that the dGPU stays off the PCI bus and `dgpu_disable` reads `1`;
  - leaving Eco for Standard and for Ultimate lands in that mode, not back in Eco;
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
- Recovery documented in the README, from a TTY:
  - Ultimate stuck: `echo 1 | sudo tee /sys/class/firmware-attributes/asus-armoury/attributes/gpu_mux_mode/current_value`, or set the MUX to Optimus/Dynamic in the BIOS, then reboot.
  - Eco stuck: `echo 0 | sudo tee /sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value` and/or set `"hotplug_type": "None"` in `/etc/supergfxd.conf` (with `None` the safety check clears `dgpu_disable` and boots Hybrid), then reboot.
  - A kernel cmdline `supergfxd.mode=` is persisted into the config by supergfxd, so it is not a one-boot override.

## Left to the builder

- File and module layout within the nightlight pattern; icons; exact UI copy (wording, not meaning).
- The helper language (bash or something else), provided it meets the helper rules above.
- The polkit action id, message text and install paths.
