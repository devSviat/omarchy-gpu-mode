import { test } from "node:test"
import assert from "node:assert/strict"
import { loadModel } from "./load-model.mjs"

const M = loadModel()
const REPO = "/home/u/omarchy-gpu-mode"
const INSTALL = "sudo " + REPO + "/install-root.sh"

function state(over) {
  return Object.assign({
    version: 1, active: "standard", configured: "standard", inconsistent: false,
    mux: 1, muxPendingReboot: false, dgpuDisabled: false, externalConnected: [],
    stockHookPresent: false, helper: "current", error: ""
  }, over || {})
}

test("modeInfo copy", () => {
  assert.deepEqual(Array.from(M.modeIds), ["eco", "standard", "ultimate"])
  const eco = M.modeInfo("eco")
  assert.equal(eco.label, "Eco")
  assert.equal(eco.tag, "iGPU only")
  assert.equal(eco.description, "The NVIDIA GPU is powered off. Best battery life; games and CUDA cannot see it.")
  assert.equal(M.modeInfo("standard").tag, "Hybrid")
  assert.equal(M.modeInfo("standard").description, "Intel drives the screen and the NVIDIA GPU wakes on demand.")
  assert.equal(M.modeInfo("ultimate").tag, "dGPU only")
  assert.equal(M.modeInfo("ultimate").description, "The NVIDIA GPU drives the screen directly. Best performance, highest power draw.")
  for (const id of M.modeIds) assert.ok(M.modeInfo(id).icon.length > 0)
})

test("parseState rejects garbage", () => {
  assert.equal(M.parseState(""), null)
  assert.equal(M.parseState("{}"), null)
  assert.equal(M.parseState('{"version":2,"active":"eco"}'), null)
  assert.equal(M.parseState('{"version":1,"active":"bogus"}'), null)
  assert.equal(M.parseState("not json"), null)
  assert.equal(M.parseState('{"version":1,"active":"eco"}').active, "eco")
})

test("viewFor disables apply on the active mode", () => {
  assert.equal(M.viewFor(state(), "standard", REPO).canApply, false)
  assert.equal(M.viewFor(state(), "eco", REPO).canApply, true)
  assert.equal(M.viewFor(state(), "eco", REPO).banner, "none")
  assert.equal(M.viewFor(state(), "eco", REPO).bannerText, "")
})

test("viewFor currentText", () => {
  assert.equal(M.viewFor(state(), "eco", REPO).currentText, "Now: Standard")
})

test("viewFor shows helper banners", () => {
  const m = M.viewFor(state({ helper: "missing" }), "eco", REPO)
  assert.equal(m.banner, "helper-missing")
  assert.equal(m.canApply, false)
  assert.equal(m.bannerText, "The root helper is not installed. Run: " + INSTALL)
  const o = M.viewFor(state({ helper: "outdated" }), "eco", REPO)
  assert.equal(o.banner, "helper-outdated")
  assert.equal(o.canApply, false)
  assert.equal(o.bannerText, "The root helper differs from this checkout. Review the changes, then run: " + INSTALL)
})

test("viewFor inconsistent", () => {
  const v = M.viewFor(state({ inconsistent: true }), "eco", REPO)
  assert.equal(v.banner, "inconsistent")
  assert.equal(v.bannerText, "A GPU switch is waiting for a reboot.")
  assert.equal(v.canApply, false)
})

test("viewFor error banner", () => {
  const v = M.viewFor(state({ error: "config unreadable" }), "eco", REPO)
  assert.equal(v.banner, "error")
  assert.equal(v.bannerText, "config unreadable")
  assert.equal(v.canApply, false)
})

test("viewFor banner priority", () => {
  const all = state({ helper: "missing", error: "x", inconsistent: true })
  assert.equal(M.viewFor(all, "eco", REPO).banner, "helper-missing")
  assert.equal(M.viewFor(state({ helper: "outdated", error: "x", inconsistent: true }), "eco", REPO).banner, "helper-outdated")
  assert.equal(M.viewFor(state({ error: "x", inconsistent: true }), "eco", REPO).banner, "error")
})

test("monitor warning only for eco with connections", () => {
  const s = state({ externalConnected: ["HDMI-A-1"] })
  const v = M.viewFor(s, "eco", REPO)
  assert.equal(v.showMonitorWarning, true)
  assert.equal(v.monitorText, "HDMI-A-1 is connected. External outputs stop working in Eco.")
  assert.equal(M.viewFor(s, "standard", REPO).showMonitorWarning, false)
  assert.equal(M.viewFor(state(), "eco", REPO).showMonitorWarning, false)
  const two = M.viewFor(state({ externalConnected: ["HDMI-A-1", "DP-2"] }), "eco", REPO)
  assert.equal(two.monitorText, "HDMI-A-1, DP-2 is connected. External outputs stop working in Eco.")
})

test("noticeFor stock hook", () => {
  const text = "Omarchy's force-igpu sleep hook is back next to GPU Mode's. Run: " + INSTALL
  assert.equal(M.noticeFor(state({ active: "eco", stockHookPresent: true }), REPO), text)
  assert.equal(M.noticeFor(state({ active: "standard", stockHookPresent: true }), REPO), "")
  assert.equal(M.noticeFor(state({ active: "eco", stockHookPresent: false }), REPO), "")
})

test("classifyHelperExit treats 126/127 as dismissed", () => {
  assert.equal(M.classifyHelperExit(0, "").kind, "ok")
  assert.equal(M.classifyHelperExit(126, "").kind, "dismissed")
  assert.equal(M.classifyHelperExit(127, "").kind, "dismissed")
  const e = M.classifyHelperExit(1, "gpu-mode: config unreadable\n")
  assert.equal(e.kind, "error")
  assert.equal(e.message, "gpu-mode: config unreadable")
})

test("applyGuard blocks a second apply while busy", () => {
  assert.equal(M.applyGuard(true), false)
  assert.equal(M.applyGuard(false), true)
})
