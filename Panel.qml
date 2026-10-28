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
  property var state: null
  property string selected: "standard"
  property string message: ""
  property string pendingMode: ""
  property bool reverting: false

  readonly property string repoDir: {
    var path = String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "").replace(/\/+$/, "")
    try { return decodeURIComponent(path) } catch (e) { return path }
  }
  readonly property var view: state ? Model.viewFor(state, selected, repoDir) : null
  readonly property bool inconsistent: view !== null && view.banner === "inconsistent"
  readonly property string notice: state ? Model.noticeFor(state, repoDir) : ""
  readonly property bool canPrimary: !busy && view !== null && (inconsistent || view.canApply)
  readonly property string statusLine: message !== "" ? message : (view ? view.bannerText : "")
  readonly property string fontFamily: Style.font.family

  function open(payloadJson) {
    root.message = ""
    root.busy = false
    root.reverting = false
    root.opened = true
    loadState()
    Qt.callLater(function() {
      if (root.opened) keyCatcher.forceActiveFocus()
    })
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

  function loadState() {
    if (stateProc.running) return
    stateProc.command = [root.repoDir + "/libexec/gpu-mode", "state"]
    stateProc.running = true
  }

  function applyState(raw) {
    var parsed = Model.parseState(raw)
    if (parsed === null) {
      root.state = null
      root.message = "Could not read the GPU state."
      return
    }
    root.state = parsed
    root.selected = parsed.active
  }

  function moveSelection(dx) {
    if (root.busy || dx === 0) return
    var ids = Model.modeIds
    var index = ids.indexOf(root.selected)
    root.selected = ids[Math.max(0, Math.min(ids.length - 1, index + dx))]
  }

  function runHelper(mode, isRevert) {
    if (!Model.applyGuard(root.busy)) return
    root.busy = true
    root.message = ""
    root.pendingMode = mode
    root.reverting = isRevert
    helperProc.stderrText = ""
    helperProc.exitCode = -1
    helperProc.streamDone = false
    helperProc.command = ["pkexec", "/usr/local/libexec/omarchy-gpu-mode/gpu-mode", "apply", mode]
    helperProc.running = true
  }

  function primaryAction() {
    if (!root.canPrimary) return
    if (root.inconsistent) startReboot()
    else runHelper(root.selected, false)
  }

  function secondaryAction() {
    if (root.busy) return
    if (root.inconsistent) runHelper(root.state.active, true)
    else dismiss()
  }

  function startReboot() {
    root.busy = true
    root.message = ""
    rebootProc.command = ["/usr/bin/omarchy-system-reboot"]
    rebootProc.running = true
  }

  function helperFinished() {
    var result = Model.classifyHelperExit(helperProc.exitCode, helperProc.stderrText)
    if (root.reverting) {
      root.busy = false
      root.reverting = false
      root.message = result.kind === "ok"
        ? "Could not schedule the reboot; the switch was reverted."
        : (result.message || "Could not revert the switch.")
      loadState()
      return
    }
    if (result.kind === "ok") {
      startReboot()
      return
    }
    root.busy = false
    if (result.kind === "error") root.message = result.message || "The GPU switch failed."
  }

  function rebootFinished(code) {
    if (code === 0) return
    if (root.inconsistent || !root.state) {
      root.busy = false
      root.message = "Could not schedule the reboot."
      return
    }
    root.busy = false
    runHelper(root.state.active, true)
  }

  Process {
    id: stateProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (root.opened) root.applyState(text)
    }
    onExited: function(exitCode) {
      if (root.opened && exitCode !== 0 && root.state === null)
        root.message = "Could not read the GPU state."
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
  }

  Process {
    id: rebootProc
    onExited: function(code) { root.rebootFinished(code) }
  }

  PanelWindow {
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "sviat-gpu-mode"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    Rectangle {
      anchors.fill: parent
      color: Util.alpha(Color.background, 0.7)

      MouseArea {
        anchors.fill: parent
        onClicked: if (!root.busy) root.dismiss()
      }
    }

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: if (!root.busy) root.dismiss()
      onMoveRequested: function(dx, dy) { root.moveSelection(dx) }
      onReturnRequested: root.primaryAction()

      Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(Style.space(460), parent.width - Style.space(32))
        height: content.implicitHeight + Style.space(40)
        color: Color.popups.background
        border.color: Color.popups.border
        border.width: Style.normalBorderWidth
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
                readonly property bool current: root.state !== null && root.state.active === modelData
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
            visible: root.statusLine !== ""
            textFormat: Text.PlainText
            text: root.statusLine
            color: Color.urgent
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
