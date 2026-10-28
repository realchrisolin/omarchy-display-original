import QtQuick
import qs.Ui
import qs.Commons
import "Model.js" as Model

// Embeddable MIRACAST block for the v2 Display panel (kris-1 host).
// Primary controls only; encode/radio stay in DisplayPanel.qml (v1) for now.
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
  readonly property var posValues: ["left", "above", "below", "right"]
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

  function posLabel(pos) {
    if (pos === "left") return "Left"
    if (pos === "above") return "Above"
    if (pos === "below") return "Below"
    return "Right"
  }

  function handleTextKey(text) {
    var t = String(text || "")
    if (t === "s" || t === "S") { miracast.scanPeers(); return true }
    if (t === "d" || t === "D") { miracast.runDoctor(true); return true }
    if (t === "i" || t === "I") { root.helpRequested(); return true }
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

  Connections {
    target: miracast
    function onPhaseChanged() {
      if (miracast.active) root.expanded = true
    }
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(miracastHdr.implicitHeight, collapsedActions.implicitHeight)

    MouseArea {
      anchors.left: parent.left
      anchors.right: collapsedActions.visible ? collapsedActions.left : parent.right
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      anchors.rightMargin: collapsedActions.visible ? Style.spacing.sm : 0
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        root.expanded = !root.expanded
        root.focusRequested()
      }
    }

    Row {
      id: miracastHdr
      anchors.left: parent.left
      anchors.right: collapsedActions.visible ? collapsedActions.left : parent.right
      anchors.rightMargin: collapsedActions.visible ? Style.spacing.sm : 0
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.sm

      Text {
        text: root.expanded ? "󰅀" : "󰅂"
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.body
        anchors.verticalCenter: parent.verticalCenter
      }

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
        visible: !root.expanded
        width: Math.max(0, miracastHdr.width - miracastTitle.x - miracastTitle.width - miracastHdr.spacing)
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
      visible: !root.expanded
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
        onClicked: miracast.scanPeers()
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
    x: Style.space(10)
    width: parent.width - Style.space(10)
    spacing: Style.space(4)
    visible: root.expanded && !miracast.active

    Text {
      text: "STATUS"
      color: Qt.darker(root.bar.foreground, 1.25)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Text {
      width: parent.width
      text: Model.miracastPhaseLabel(
              miracast.phase,
              miracast.p2pWifiResolved,
              miracast.p2pWifiAdapterName).toUpperCase()
      color: Qt.darker(root.bar.foreground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      wrapMode: Text.WordWrap
    }

    Text {
      readonly property string detail: {
        if (miracast.lastError !== "" && miracast.actionStatus === "")
          return miracast.lastError
        if (miracast.actionStatus !== "")
          return miracast.actionStatus
        return miracast.statusText
      }
      visible: detail !== ""
      width: parent.width
      text: detail
      color: miracast.lastError !== "" && miracast.actionStatus === ""
             ? (root.bar.urgent || root.bar.foreground)
             : Qt.darker(root.bar.foreground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }

  Text {
    x: Style.space(10)
    width: parent.width - Style.space(10)
    visible: root.expanded && miracast.active && text !== ""
    text: {
      if (miracast.lastError !== "" && miracast.actionStatus === "")
        return miracast.lastError
      if (miracast.actionStatus !== "" && String(miracast.actionStatus).indexOf("Ready") !== 0)
        return miracast.actionStatus
      return ""
    }
    color: miracast.lastError !== "" && miracast.actionStatus === ""
           ? (root.bar.urgent || root.bar.foreground)
           : Qt.darker(root.bar.foreground, 1.4)
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Column {
    x: Style.space(10)
    width: parent.width - Style.space(10)
    spacing: Style.space(6)
    visible: root.expanded

    Text {
      text: "CONTROLS"
      color: Qt.darker(root.bar.foreground, 1.25)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    CursorSurface {
      width: parent.width
      implicitHeight: actionsRow.implicitHeight + Style.spacing.controlGap
      hasCursor: root.cursorActive && root.focused
      foreground: root.bar.foreground
      outline: true

      Row {
        id: actionsRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.space(6)
        anchors.rightMargin: Style.space(6)
        spacing: Style.space(6)

        PanelActionButton {
          iconText: "󰍉"
          tooltipText: "Scan (S)"
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          enabled: !miracast.busy
          onClicked: miracast.scanPeers()
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
        Item { width: Style.space(8); height: 1 }
        PanelActionButton {
          iconText: miracast.active ? "󰓛" : "󰑐"
          tooltipText: miracast.active ? "Stop (X)" : "Reconnect (C)"
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          enabled: !miracast.busy
          onClicked: miracast.active ? miracast.stopCast() : miracast.startCast("")
        }
      }

      HoverHandler {
        onHoveredChanged: if (hovered && !root.reflowingText) root.focusRequested()
      }
    }

    Column {
      visible: miracast.active
      width: parent.width
      spacing: Style.space(4)

      Text {
        text: "CAST MODE"
        color: Qt.darker(root.bar.foreground, 1.25)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Row {
        width: parent.width
        spacing: Style.spacing.xs
        Repeater {
          model: root.modeValues
          Button {
            required property string modelData
            text: modelData === "extend" ? "Extend" : "Mirror"
            fontSize: Style.font.caption
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            horizontalPadding: Style.spacing.sm
            verticalPadding: Style.spacing.controlPaddingY
            bordered: true
            active: miracast.mode === modelData
            onClicked: miracast.setMode(modelData)
          }
        }
      }

      Column {
        visible: miracast.mode === "extend"
        width: parent.width
        spacing: Style.space(4)

        Text {
          text: "EXTEND POSITION"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Row {
          width: parent.width
          spacing: Style.spacing.xs
          Repeater {
            model: root.posValues
            Button {
              required property string modelData
              text: root.posLabel(modelData)
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              horizontalPadding: Style.spacing.sm
              verticalPadding: Style.spacing.controlPaddingY
              bordered: true
              active: miracast.extendPosition === modelData
              onClicked: miracast.setExtendPosition(modelData)
            }
          }
        }
      }
    }
  }

  Column {
    x: Style.space(10)
    width: parent.width - Style.space(10)
    spacing: Style.space(4)
    visible: root.expanded

    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Text {
        text: miracast.preserveDisplayAcrossMonitors ? "󰄬" : "󰄱"
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.body
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: miracast.setPreserveDisplayAcrossMonitors(!miracast.preserveDisplayAcrossMonitors)
        }
      }
      Text {
        text: "Persist display across monitors"
        color: Qt.darker(root.bar.foreground, 1.15)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        width: parent.width - parent.spacing - 28
        wrapMode: Text.WordWrap
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: miracast.setPreserveDisplayAcrossMonitors(!miracast.preserveDisplayAcrossMonitors)
        }
      }
    }

    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Text {
        text: miracast.autoSwitchAudioOutput ? "󰄬" : "󰄱"
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.body
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: miracast.setAutoSwitchAudioOutput(!miracast.autoSwitchAudioOutput)
        }
      }
      Text {
        text: "Automatically switch audio output"
        color: Qt.darker(root.bar.foreground, 1.15)
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        width: parent.width - parent.spacing - 28
        wrapMode: Text.WordWrap
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: miracast.setAutoSwitchAudioOutput(!miracast.autoSwitchAudioOutput)
        }
      }
    }
  }

  Column {
    id: advancedBox
    x: Style.space(10)
    width: parent.width - Style.space(10)
    spacing: Style.space(4)
    visible: root.expanded
    property bool expanded: false

    Item {
      width: parent.width
      implicitHeight: advHdr.implicitHeight
      Row {
        id: advHdr
        width: parent.width
        spacing: Style.spacing.sm
        Text {
          text: advancedBox.expanded ? "󰅀" : "󰅂"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
        }
        Text {
          text: "ADVANCED SETTINGS"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: advancedBox.expanded = !advancedBox.expanded
      }
    }

    Column {
      visible: advancedBox.expanded
      width: parent.width
      spacing: Style.space(6)

      Column {
        width: parent.width
        spacing: Style.space(4)
        visible: miracast.streamModes && miracast.streamModes.length > 0
        Text {
          text: "STREAM MODE"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
        Flow {
          width: parent.width
          spacing: Style.spacing.xs
          Repeater {
            model: miracast.streamModes
            Button {
              required property var modelData
              text: miracast.streamModeLabel(modelData && modelData.id)
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              active: miracast.streamMode === (modelData && modelData.id)
              enabled: !miracast.busy
              onClicked: miracast.setStreamMode(modelData ? modelData.id : "")
            }
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(4)
        Text {
          text: "ENCODING STRATEGY"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
        Row {
          spacing: Style.spacing.xs
          Repeater {
            model: Model.miracastEncodeStrategyValues()
            Button {
              required property string modelData
              text: Model.miracastEncodeStrategyLabel(modelData)
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              active: miracast.encodeStrategy === modelData
              onClicked: miracast.setEncodeStrategy(modelData)
            }
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(4)
        Text {
          text: "RENDER ENGINE"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
        Row {
          spacing: Style.spacing.xs
          Repeater {
            model: Model.miracastCaptureEncodeValues()
            Button {
              required property string modelData
              text: Model.miracastCaptureEncodePillTitle(modelData)
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              active: miracast.captureEncode === modelData
              onClicked: miracast.setCaptureEncode(modelData)
            }
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(4)
        Text {
          text: "PRESET QUALITY"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
        Flow {
          width: parent.width
          spacing: Style.spacing.xs
          Repeater {
            model: Model.miracastEncodeProfileValues()
            Button {
              required property string modelData
              text: Model.miracastEncodeProfileLabel(modelData)
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              active: miracast.encodeProfile === modelData
              onClicked: miracast.setEncodeProfile(modelData)
            }
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(4)
        visible: miracast.p2pWifiPrimaryValues && miracast.p2pWifiPrimaryValues.length > 0
        Text {
          text: "RADIO"
          color: Qt.darker(root.bar.foreground, 1.25)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
        Flow {
          width: parent.width
          spacing: Style.spacing.xs
          Repeater {
            model: miracast.p2pWifiPrimaryValues
            Button {
              required property string modelData
              text: modelData === "auto" ? "Auto" : modelData
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              active: miracast.p2pWifiInterface === modelData
              onClicked: miracast.setP2pWifiInterface(modelData)
            }
          }
        }
      }
    }
  }

  Column {
    visible: root.expanded && miracast.peers && miracast.peers.length > 0
    x: Style.space(10)
    width: parent.width - Style.space(10)
    spacing: Style.space(6)

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
