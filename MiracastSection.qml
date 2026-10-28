import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

// Single-line MIRACAST row: summary + Scan / Doctor / Info / Start-Stop.
// Stream/encode/radio and persist/audio live on the Miracast tile properties modal.
Column {
  id: root
  spacing: Style.space(10)

  required property QtObject bar
  property bool active: false
  property bool focused: false
  property bool cursorActive: false
  property var panel: null
  property string pluginDir: ""
  property string monitorName: "eDP-1"
  property bool reflowingText: false

  readonly property var modeValues: ["mirror", "extend"]
  readonly property bool available: true
  property bool expanded: false

  readonly property string collapsedSummary: {
    if (miracast.active)
      return Model.miracastConnectionSummary(
        miracast.phase, miracast.lastPeerName, miracast.lastPeerMac,
        miracast.mode, miracast.p2pFreqMHz)
    var phase = Model.miracastPhaseLabel(
      miracast.phase, miracast.p2pWifiResolved, miracast.p2pWifiAdapterName)
    return phase || "Idle"
  }

  signal focusRequested()
  signal helpRequested()

  function scan() {
    root.expanded = true
    miracast.scanPeers()
  }

  function handleTextKey(text) {
    var t = String(text || "")
    if (t === "s" || t === "S") { root.scan(); return true }
    if (t === "d" || t === "D") { miracast.runDoctor(true); return true }
    if (t === "c" || t === "C") { if (!miracast.active) miracast.startCast(""); return true }
    if (t === "x" || t === "X") { if (miracast.active) miracast.stopCast(); return true }
    if (t === "m" || t === "M") { miracast.setMode("mirror"); return true }
    if (t === "e" || t === "E") { miracast.setMode("extend"); return true }
    return false
  }

  MiracastService {
    id: miracast
    pluginDir: root.pluginDir
    monitorName: root.monitorName
  }

  readonly property var service: miracast

  Item {
    width: parent.width
    implicitHeight: Math.max(miracastHdr.implicitHeight, collapsedActions.implicitHeight)

    HoverHandler {
      onHoveredChanged: if (hovered && !root.reflowingText) root.focusRequested()
    }

    Row {
      id: miracastHdr
      anchors.left: parent.left
      anchors.right: collapsedActions.left
      anchors.rightMargin: Style.spacing.sm
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.sm

      Text {
        id: miracastTitle
        text: "MIRACAST"
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.2
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        width: Math.max(0, miracastHdr.width - miracastTitle.width - miracastHdr.spacing)
        text: root.collapsedSummary.toUpperCase()
        color: Qt.darker(root.bar.foreground, 1.4)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
      }
    }

    Row {
      id: collapsedActions
      spacing: Style.space(4)
      z: 1
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter

      PanelActionButton {
        iconText: "󰍉"
        tooltipText: "Scan (S)"
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        enabled: !miracast.busy
        onClicked: root.scan()
      }
      PanelActionButton {
        iconText: "󰓙"
        tooltipText: "Doctor (D)"
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        enabled: !miracast.busy
        onClicked: miracast.runDoctor(true)
      }
      PanelActionButton {
        iconText: "󰋽"
        tooltipText: "Info (I)"
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        onClicked: root.helpRequested()
      }
      PanelActionButton {
        iconText: miracast.active ? "󰓛" : "󰑐"
        tooltipText: miracast.active ? "Stop (X)" : "Reconnect (C)"
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        enabled: !miracast.busy
        onClicked: miracast.active ? miracast.stopCast() : miracast.startCast("")
      }
    }
  }

  Column {
    visible: root.expanded
    x: Style.space(10)
    width: parent.width - Style.space(10)
    spacing: Style.space(6)

    Text {
      visible: !miracast.peers || miracast.peers.length === 0
      width: parent.width
      text: (miracast.busy ? miracast.actionStatus || "SCANNING…" : miracast.lastError || miracast.statusText || "NO DISPLAYS FOUND").toUpperCase()
      color: Qt.darker(root.bar.foreground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      wrapMode: Text.WordWrap
    }

    Repeater {
      model: miracast.peers
      CursorSurface {
        required property var modelData
        width: parent.width
        implicitHeight: peerInner.implicitHeight + Style.spacing.xl
        foreground: root.bar.foreground
        fill: Style.hoverFillFor(root.bar.foreground, Color.accent)

        Row {
          id: peerInner
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(8)

          Text {
            text: "󰑋"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.title
            width: Style.space(22)
            horizontalAlignment: Text.AlignHCenter
            anchors.verticalCenter: parent.verticalCenter
          }
          Column {
            width: parent.width - Style.space(22) - Style.space(8)
            spacing: Style.space(1)
            Text {
              width: parent.width
              text: Model.miracastPeerTitle(modelData)
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: Text.WordWrap
            }
            Text {
              width: parent.width
              text: Model.miracastPeerSubtitle(modelData)
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }
        }

        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: miracast.startCast(modelData ? modelData.mac : "")
        }
      }
    }
  }
}
