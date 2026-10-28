import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "LayoutModel.js" as LayoutModel

// Always-on layout host, parented by DisplayLayoutPanel (bar widget).
// Not a separate plugin service: Qt reports "File name case mismatch" when
// createComponent loads through the realchrisolin.monitor symlink.
// Keeps physical monitors in the saved left-to-right order. Miracast virtual
// heads (persistent-miracast / HEADLESS*) are skipped in LayoutModel.isArrangeable.
// Holds apply during P2P/RTSP handshake. After each apply, re-places or parks
// the Extend head via miracast-ctl place-virtual-head.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string orderPath: Quickshell.env("HOME") + "/.config/omarchy/monitor-layout.json"
  readonly property string statusPath: Quickshell.env("HOME") + "/.local/state/omarchy-miracast/status.json"
  readonly property string lockPath: Quickshell.env("HOME") + "/.local/state/omarchy-miracast/connecting.lock"
  readonly property string pluginDir: {
    var s = String(Qt.resolvedUrl("./"))
    if (s.indexOf("file://") === 0)
      s = decodeURIComponent(s.substring(7))
    while (s.length > 1 && s.charAt(s.length - 1) === "/")
      s = s.substring(0, s.length - 1)
    return s
  }
  readonly property string ctl: pluginDir + "/bin/miracast-ctl"

  function parseStatus() {
    try {
      return JSON.parse(statusFile.text() || "{}")
    } catch (e) {
      return {}
    }
  }

  LayoutApplier {
    id: applier
    orderPath: root.orderPath
    manageExternalMode: true
    onApplied: {
      if (!placeProc.running)
        placeProc.running = true
    }
  }

  Timer {
    id: settle
    interval: 300
    repeat: false
    onTriggered: {
      var st = root.parseStatus()
      if (LayoutModel.shouldHoldLayout(st, lockFile.loaded))
        return
      applier.apply()
    }
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event || !event.name) return
      switch (String(event.name)) {
      case "monitoradded":
      case "monitoraddedv2":
      case "monitorremoved":
      case "monitorremovedv2":
      case "configreloaded":
        settle.restart()
        break
      }
    }
  }

  FileView {
    path: root.orderPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: settle.restart()
  }

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
  }

  FileView {
    id: lockFile
    path: root.lockPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
  }

  Process {
    id: placeProc
    command: [root.ctl, "place-virtual-head"]
    stdout: StdioCollector { waitForEnd: true }
  }

  Component.onCompleted: settle.restart()
}
