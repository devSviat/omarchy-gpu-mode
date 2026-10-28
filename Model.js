.pragma library

var modeIds = ["eco", "standard", "ultimate"]

var MODES = {
    eco: {
        id: "eco",
        label: "Eco",
        icon: "\u{F032A}",
        tag: "iGPU only",
        description: "The NVIDIA GPU is powered off. Best battery life; games and CUDA cannot see it."
    },
    standard: {
        id: "standard",
        label: "Standard",
        icon: "\u{F061A}",
        tag: "Hybrid",
        description: "Intel drives the screen and the NVIDIA GPU wakes on demand."
    },
    ultimate: {
        id: "ultimate",
        label: "Ultimate",
        icon: "\u{F0297}",
        tag: "dGPU only",
        description: "The NVIDIA GPU drives the screen directly. Best performance, highest power draw."
    }
}

function modeInfo(id) {
    return MODES[id] || null
}

function parseState(raw) {
    var state
    try {
        state = JSON.parse(raw)
    } catch (e) {
        return null
    }
    if (!state || state.version !== 1 || !MODES.hasOwnProperty(state.active))
        return null
    return state
}

function installCommand(repoDir) {
    return "sudo " + repoDir + "/install-root.sh"
}

function viewFor(state, selected, repoDir) {
    var banner = "none"
    var bannerText = ""
    if (state.helper === "missing") {
        banner = "helper-missing"
        bannerText = "The root helper is not installed. Run: " + installCommand(repoDir)
    } else if (state.helper === "outdated") {
        banner = "helper-outdated"
        bannerText = "The root helper is out of date. Run: " + installCommand(repoDir)
    } else if (state.error) {
        banner = "error"
        bannerText = state.error
    } else if (state.inconsistent) {
        banner = "inconsistent"
        bannerText = "A GPU switch is waiting for a reboot."
    }

    var external = state.externalConnected || []
    var showMonitorWarning = selected === "eco" && external.length > 0

    return {
        banner: banner,
        bannerText: bannerText,
        canApply: banner === "none" && selected !== state.active,
        showMonitorWarning: showMonitorWarning,
        monitorText: showMonitorWarning
            ? external.join(", ") + " is connected. External outputs stop working in Eco."
            : "",
        currentText: "Now: " + MODES[state.active].label
    }
}

function noticeFor(state, repoDir) {
    if (!state.stockHookPresent || state.active !== "eco")
        return ""
    return "Omarchy's force-igpu sleep hook is back next to GPU Mode's. Run: " + installCommand(repoDir)
}

// 126/127 come from pkexec when the user dismisses the auth dialog or none is available.
function classifyHelperExit(code, stderr) {
    var message = String(stderr || "").trim()
    if (code === 0)
        return { kind: "ok", message: "" }
    if (code === 126 || code === 127)
        return { kind: "dismissed", message: message }
    return { kind: "error", message: message }
}

function applyGuard(busy) {
    return !busy
}
