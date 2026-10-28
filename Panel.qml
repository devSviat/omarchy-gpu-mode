import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Model.js" as Model

Item {
  id: root

  property var shell: null
  property var manifest: null

  property bool opened: false
  property bool busy: false
  property var gpuState: null
  property string selected: "standard"
  property string message: ""
  property bool messageInfo: false
  property bool rebootScheduled: false
  property string phase: ""
  property string revertTarget: ""

  readonly property string repoDir: {
    var path = String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "").replace(/\/+$/, "")
    try { return decodeURIComponent(path) } catch (e) { return path }
  }
  readonly property var view: gpuState ? Model.viewFor(gpuState, selected, repoDir) : null
  readonly property bool inconsistent: view !== null && view.banner === "inconsistent"
  readonly property string notice: gpuState ? Model.noticeFor(gpuState, repoDir) : ""
  readonly property bool canPrimary: !busy && !rebootScheduled && view !== null
    && (inconsistent || view.canApply)
  readonly property string bannerText: view ? view.bannerText : ""
  readonly property string fontFamily: Style.font.family

  function focusKeys() {
    Qt.callLater(function() {
      if (root.opened) keyCatcher.forceActiveFocus()
    })
  }

  function say(text, info) {
    root.message = text
    root.messageInfo = info === true
  }

  function open(payloadJson) {
    if (helperProc.running || rebootProc.running) {
      root.opened = true
      focusKeys()
      return
    }
    say("")
    root.rebootScheduled = false
    root.phase = ""
    root.busy = false
    root.opened = true
    loadState()
    focusKeys()
  }

  function close() {
    root.opened = false
    if (stateProc.running) stateProc.running = false
  }

  function dismiss() {
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "sviat.gpu-mode")
    else close()
  }

  // Hiding unloads this Item, so the result of an in-flight action would be lost;
  // the user shell cannot signal the root helper to stop.
  function dismissIfIdle() {
    if (!root.busy) dismiss()
  }

  function loadState() {
    if (stateProc.running) return
    stateProc.command = [root.repoDir + "/libexec/gpu-mode", "state"]
    stateProc.running = true
  }

  function applyState(raw) {
    if (root.busy) return
    var parsed = Model.parseState(raw)
    if (parsed === null) {
      root.gpuState = null
      say("Could not read the GPU state.")
      return
    }
    root.gpuState = parsed
    root.selected = parsed.active
  }

  function moveSelection(dx) {
    if (root.busy || dx === 0) return
    var ids = Model.modeIds
    var index = ids.indexOf(root.selected)
    root.selected = ids[Math.max(0, Math.min(ids.length - 1, index + dx))]
  }

  function runHelper(mode, nextPhase) {
    if (!Model.applyGuard(root.busy)) return
    root.busy = true
    say("")
    root.phase = nextPhase
    helperProc.stderrText = ""
    helperProc.exitCode = -1
    helperProc.streamDone = false
    helperProc.command = ["/usr/bin/pkexec", "/usr/local/libexec/omarchy-gpu-mode/gpu-mode", "apply", mode]
    helperProc.running = true
  }

  function startReboot(nextPhase) {
    root.busy = true
    say("")
    root.phase = nextPhase
    rebootProc.exitCode = -1
    rebootProc.command = ["/usr/bin/omarchy-system-reboot"]
    rebootProc.running = true
  }

  function primaryAction() {
    if (!root.canPrimary) return
    if (root.inconsistent) {
      startReboot("reboot-only")
    } else {
      root.revertTarget = root.gpuState.active
      runHelper(root.selected, "apply")
    }
  }

  function secondaryAction() {
    if (root.busy) return
    if (root.inconsistent) runHelper(root.gpuState.active, "revert-manual")
    else dismiss()
  }

  function helperFinished() {
    var result = Model.classifyHelperExit(helperProc.exitCode, helperProc.stderrText)
    var finished = root.phase
    root.busy = false
    root.phase = ""
    if (finished === "apply") {
      if (result.kind === "ok") startReboot("reboot-after-apply")
      else if (result.kind === "error") say(result.message || "The GPU switch failed.")
      return
    }
    if (finished === "revert-manual") {
      if (result.kind === "ok") {
        say("The pending switch was reverted.", true)
        loadState()
      } else if (result.kind === "error") {
        say(result.message || "Could not revert the switch.")
      }
      return
    }
    if (finished === "revert-after-reboot-failure") {
      if (result.kind === "ok") {
        say("Could not schedule the reboot; the switch was reverted.")
        loadState()
      } else {
        say("Could not schedule the reboot, and the revert failed: "
          + (result.message || "authentication was dismissed")
          + ". The new mode will apply at the next reboot.")
      }
    }
  }

  function rebootFinished(code, failureMessage) {
    var finished = root.phase
    root.busy = false
    root.phase = ""
    if (code === 0) {
      root.rebootScheduled = true
      say("Rebooting…", true)
      return
    }
    if (finished === "reboot-after-apply") runHelper(root.revertTarget, "revert-after-reboot-failure")
    else say(failureMessage || "Could not schedule the reboot.")
  }

  function processStopped(failureMessage) {
    root.busy = false
    root.phase = ""
    say(failureMessage)
  }

  Process {
    id: stateProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (root.opened) root.applyState(text)
    }
    onExited: function(exitCode) {
      if (root.opened && exitCode !== 0 && root.gpuState === null)
        root.say("Could not read the GPU state.")
    }
  }

  Process {
    id: helperProc
    property string stderrText: ""
    property int exitCode: -1
    property bool streamDone: false

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        helperProc.stderrText = text
        helperProc.streamDone = true
        if (helperProc.exitCode >= 0) root.helperFinished()
      }
    }
    onExited: function(code) {
      helperProc.exitCode = code
      if (helperProc.streamDone) root.helperFinished()
    }
    onRunningChanged: {
      if (running) return
      root.focusKeys()
      Qt.callLater(function() {
        if (helperProc.exitCode < 0 && root.busy && root.phase !== "reboot-after-apply")
          root.processStopped("Could not start the privileged helper.")
      })
    }
  }

  Process {
    id: rebootProc
    property int exitCode: -1

    onExited: function(code) {
      rebootProc.exitCode = code
      root.rebootFinished(code)
    }
    onRunningChanged: {
      if (running) return
      Qt.callLater(function() {
        if (rebootProc.exitCode < 0 && root.busy && root.phase.indexOf("reboot") === 0)
          root.rebootFinished(-1, "Could not run the reboot command.")
      })
    }
  }

  PanelWindow {
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-keyboard-panel"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: helperProc.running ? WlrKeyboardFocus.None : WlrKeyboardFocus.Exclusive

    Rectangle {
      anchors.fill: parent
      color: Color.menu.scrim

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismissIfIdle()
      }
    }

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.dismissIfIdle()
      onMoveRequested: function(dx, dy) { root.moveSelection(dx) }
      onReturnRequested: root.primaryAction()

      BorderSurface {
        id: card
        anchors.centerIn: parent
        width: Math.min(Style.space(460), parent.width - Style.space(32))
        height: content.implicitHeight + Style.space(40)
        color: Color.popups.background
        borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
        radius: Style.cornerRadius

        MouseArea { anchors.fill: parent; onClicked: {} }

        ColumnLayout {
          id: content
          anchors.fill: parent
          anchors.margins: Style.space(20)
          spacing: Style.space(14)

          RowLayout {
            Layout.fillWidth: true

            Text {
              text: "GPU Mode"
              color: Color.popups.text
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              Layout.fillWidth: true
            }

            Text {
              textFormat: Text.PlainText
              text: root.view ? root.view.currentText : ""
              color: Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }

          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(10)

            Repeater {
              model: Model.modeIds

              ColumnLayout {
                id: modeItem
                required property string modelData
                readonly property var info: Model.modeInfo(modelData)
                readonly property bool current: root.gpuState !== null && root.gpuState.active === modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: Style.space(4)

                Button {
                  Layout.fillWidth: true
                  text: modeItem.info.label
                  iconText: modeItem.info.icon
                  bordered: true
                  selected: root.selected === modeItem.modelData
                  enabled: !root.busy
                  verticalPadding: Style.space(12)
                  onClicked: root.selected = modeItem.modelData
                }

                Text {
                  Layout.fillWidth: true
                  text: modeItem.current ? "current" : modeItem.info.tag
                  color: modeItem.current ? Color.accent : Color.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: modeItem.current
                  horizontalAlignment: Text.AlignHCenter
                }
              }
            }
          }

          Text {
            Layout.fillWidth: true
            text: Model.modeInfo(root.selected).description
            color: Color.popups.text
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          Text {
            Layout.fillWidth: true
            visible: root.view !== null && root.view.showMonitorWarning
            textFormat: Text.PlainText
            text: root.view ? root.view.monitorText : ""
            color: Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          Text {
            Layout.fillWidth: true
            visible: root.bannerText !== ""
            textFormat: Text.PlainText
            text: root.bannerText
            color: Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          Text {
            Layout.fillWidth: true
            visible: root.message !== ""
            textFormat: Text.PlainText
            text: root.message
            color: root.messageInfo ? Color.popups.text : Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          Text {
            Layout.fillWidth: true
            visible: root.notice !== ""
            textFormat: Text.PlainText
            text: root.notice
            color: Color.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(10)

            Item { Layout.fillWidth: true }

            Button {
              text: root.inconsistent ? "Revert" : "Cancel"
              bordered: true
              enabled: !root.busy
              opacity: enabled ? 1 : 0.5
              onClicked: root.secondaryAction()
            }

            Button {
              text: root.inconsistent ? "Reboot now" : "Apply and reboot"
              bordered: true
              selected: root.canPrimary
              enabled: root.canPrimary
              opacity: enabled ? 1 : 0.5
              iconText: root.busy ? "\u{F0453}" : ""
              iconSpinning: root.busy
              onClicked: root.primaryAction()
            }
          }
        }
      }
    }
  }
}
