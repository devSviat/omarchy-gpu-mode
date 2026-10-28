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

function joinNames(names) {
    if (names.length <= 2)
        return names.join(" and ")
    return names.slice(0, -1).join(", ") + ", and " + names[names.length - 1]
}

function viewFor(state, selected, repoDir) {
    var banner = "none"
    var bannerText = ""
    if (state.helper === "missing") {
        banner = "helper-missing"
        bannerText = "The root helper is not installed. Run: " + installCommand(repoDir)
    } else if (state.helper === "outdated") {
        banner = "helper-outdated"
        bannerText = "The root helper differs from this checkout. Review the changes, then run: "
            + installCommand(repoDir)
    } else if (state.error) {
        banner = "error"
        bannerText = state.error
    } else if (state.inconsistent) {
        banner = "inconsistent"
        var pending = modeInfo(state.pendingMode)
        bannerText = pending
            ? "A switch to " + pending.label + " is waiting for a reboot."
            : "A GPU switch is waiting for a reboot."
    }

    var external = state.externalConnected || []
    var showMonitorWarning = selected === "eco" && external.length > 0

    return {
        banner: banner,
        bannerText: bannerText,
        canApply: banner === "none" && selected !== state.active,
        showMonitorWarning: showMonitorWarning,
        monitorText: showMonitorWarning
            ? joinNames(external) + (external.length === 1 ? " is" : " are")
                + " connected. External outputs stop working in Eco."
            : "",
        currentText: "Now: " + MODES[state.active].label
    }
}

function noticeFor(state, repoDir) {
    if (!state.stockHookPresent || state.active !== "eco")
        return ""
    return "Omarchy's force-igpu sleep hook is back and conflicts with GPU Mode's Eco. Run: "
        + installCommand(repoDir)
}

// pkexec exits 126 when the user dismisses the auth dialog and 127 when
// authorisation fails or cannot be obtained.
function classifyHelperExit(code, stderr) {
    var message = String(stderr || "").trim()
    if (code === 0)
        return { kind: "ok", message: "" }
    if (code === 126)
        return { kind: "dismissed", message: message }
    if (code === 127)
        return { kind: "error", message: message || "Authorisation failed" }
    return { kind: "error", message: message }
}

function applyGuard(busy) {
    return !busy
}
