import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import qs.Ui
import qs.Commons
import "LayoutModel.js" as LayoutModel

// ARRANGEMENT section: a live, scaled preview of the
// connected displays. Drag a tile to change the left-to-right order, or drive
// it from the keyboard through moveCursor()/activate(). Double-click a tile
// (or showProperties() for the tile under the cursor) to open its properties
// window (MonitorProperties.qml). The order and the settings kept there are
// saved to ~/.config/omarchy/monitor-layout.json and applied right away;
// Service.qml keeps them applied across hotplug and config reloads.
//
// Self-contained so any panel can embed it, e.g. a Display panel:
//
//   Arrangement {
//     bar: root.bar
//     active: root.opened
//     focused: root.focusSection === "arrangement"
//     cursorActive: root.cursorActive
//     panel: panelWindow   // the KeyboardPanel, to open properties beside it
//     onFocusRequested: { root.cursorActive = true; root.focusSection = "arrangement" }
//   }
Column {
  id: root

  required property QtObject bar
  // Refresh on display events only while the host panel is open.
  property bool active: false
  // The host's keyboard cursor is on this section / visible at all.
  property bool focused: false
  property bool cursorActive: false
  // Host KeyboardPanel; the properties window opens beside its card.
  property var panel: null
  // MiracastService: drag the HEADLESS tile to set extendPosition.
  property var miracast: null

  readonly property string orderPath: Quickshell.env("HOME") + "/.config/omarchy/monitor-layout.json"

  // [{ name, key, label, internal, focused, x, w, h }], left to right.
  property var tiles: []
  // Raw `hyprctl monitors all -j` output behind the tiles.
  property var monitors: []
  readonly property bool hasInternal: monitors.some(function(monitor) { return LayoutModel.isInternal(monitor) })
  // Outputs showing their Identify badge (see identify()).
  property var identifyOutputs: []
  // Output shown in the properties window ("" = closed).
  property string propertiesOutput: ""
  readonly property var propertiesTile: {
    for (var i = 0; i < tiles.length; i++)
      if (tiles[i].name === propertiesOutput) return tiles[i]
    return null
  }
  // One display still gets the section, for its settings; reordering needs two.
  readonly property bool available: tiles.length > 0
  readonly property bool reorderable: {
    var phys = 0
    var virt = 0
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].virtual) virt++
      else phys++
    }
    return phys > 1 || (phys >= 1 && virt > 0)
  }

  // Keyboard cursor over the tiles, and the tile picked up with Enter (-1 = none).
  property int selectedIndex: 0
  // The picked-up tile, by key so it survives the tiles being re-read.
  property string grabbedKey: ""
  readonly property int grabbedIndex: {
    for (var i = 0; i < tiles.length; i++)
      if (grabbedKey !== "" && tiles[i].key === grabbedKey) return i
    return -1
  }

  // Hover asks the host panel to move its keyboard focus here.
  signal focusRequested()

  Connections {
    target: root.miracast
    function onExtendPositionChanged() { if (root.active) root.refresh() }
  }

  function refresh() {
    if (!monitorsProc.running) monitorsProc.running = true
  }

  // h/l: move the cursor, or the picked-up tile along the row.
  function moveCursor(dx) {
    if (!reorderable) return
    if (grabbedIndex >= 0) {
      var tile = tiles[grabbedIndex]
      var row = rowKeys()
      var at = row.indexOf(tile.key)
      // A stacked tile joins the row beside the monitor it stood on.
      if (at === -1) at = row.indexOf(baseKey(tile.key)) + (dx > 0 ? 1 : 0)
      else at = Math.max(0, Math.min(row.length - 1, at + dx))
      saveLayout(LayoutModel.withRowPosition(orderFile.layout, tile.key, row, at))
      return
    }
    selectedIndex = Math.max(0, Math.min(tiles.length - 1, selectedIndex + dx))
  }

  // j/k while a tile is picked up: stack it below/above its row neighbour, or
  // take a stacked tile back into the row.
  function moveGrabbedVertically(dy) {
    if (grabbedIndex < 0) return
    var tile = tiles[grabbedIndex]
    var side = dy < 0 ? "above" : "below"
    if (tile.virtual) {
      var entryV = LayoutModel.activeStack(monitors, orderFile.layout.stack)[tile.key]
      if (entryV) {
        if (entryV.side !== side) {
          var rowV = rowKeys()
          saveLayout(LayoutModel.withRowPosition(orderFile.layout, tile.key, rowV,
            rowV.indexOf(baseKey(tile.key)) + 1))
        }
        return
      }
      var edp = null
      for (var v = 0; v < tiles.length; v++) {
        if (tiles[v].internal) { edp = tiles[v]; break }
      }
      if (!edp) return
      saveLayout(LayoutModel.withVirtualStacked(orderFile.layout, tile.key, edp.key, side))
      return
    }
    var entry = LayoutModel.activeStack(monitors, orderFile.layout.stack)[tile.key]
    if (entry) {
      // Moving back towards the monitor it stands on returns it to the row.
      if (entry.side !== side) {
        var row = rowKeys()
        saveLayout(LayoutModel.withRowPosition(orderFile.layout, tile.key, row,
          row.indexOf(baseKey(tile.key)) + 1))
      }
      return
    }
    var others = rowKeys().filter(function(key) { return key !== tile.key })
    if (others.length === 0) return
    var at = rowKeys().indexOf(tile.key)
    var neighbour = others[Math.max(0, Math.min(others.length - 1, at - 1))]
    saveLayout(LayoutModel.withStacked(orderFile.layout, tile.key, neighbour, side))
  }

  // Keys of the row monitors, left to right.
  function rowKeys() {
    return tiles.filter(function(tile) { return !tile.stacked })
      .sort(function(a, b) { return a.x - b.x })
      .map(function(tile) { return tile.key })
  }

  // The row monitor a stacked one ultimately stands on.
  function baseKey(key) {
    var stack = LayoutModel.activeStack(monitors, orderFile.layout.stack)
    var guard = 0
    while (stack[key] && guard++ < 64) key = stack[key].on
    return key
  }

  // Enter: pick up / drop the tile under the cursor; with a single display,
  // open its settings.
  function activate() {
    if (!available) return
    if (!reorderable) {
      showProperties()
      return
    }
    grabbedKey = grabbedIndex >= 0 ? "" : tiles[selectedIndex].key
  }

  // Extend / External only / Mirror for the laptop screen while an external
  // display is connected. The mode is saved first; Service.qml carries out
  // external-only and mirror step by step. It never acts in "extend", so
  // switching back undoes both here.
  function setExternalMode(mode) {
    if (mode !== orderFile.layout.withExternal) orderFile.saveExternalMode(mode)
    // Always, so Extend also brings back a laptop screen turned off elsewhere.
    if (mode === "extend" && !modeReset.running) modeReset.running = true
  }

  // Identify: number every display on its screen for a few seconds.
  function identify() {
    identifyOutputs = tiles.filter(function(tile) { return !tile.virtual })
      .map(function(tile) { return tile.name })
    identifyTimer.restart()
  }

  // I: open the properties of the tile under the cursor.
  function showProperties() {
    if (!available || grabbedIndex >= 0 || !tiles[selectedIndex]) return
    propertiesOutput = tiles[selectedIndex].name
  }

  // Persist per-output scale/rotation in JSON, then LayoutApplier evals,
  // rereads, and packs. Do not call omarchy-hyprland-monitor-scaling here:
  // that sed's eDP's omarchy_monitor_scale even when USB-C is focused.
  function rememberSettings(output, settings) {
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].name !== output) continue
      orderFile.saveSettings(tiles[i].key, settings)
      applier.apply()
      return
    }
    var shared = LayoutModel.sharedDescriptions(monitors)
    for (var j = 0; j < monitors.length; j++) {
      if (String(monitors[j].name) !== output) continue
      orderFile.saveSettings(LayoutModel.monitorKey(monitors[j], shared), settings)
      applier.apply()
      return
    }
  }

  function forgetSetting(output, field) {
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].name !== output) continue
      var saved = orderFile.layout.monitors[tiles[i].key]
      if (!saved || saved[field] === undefined) return
      var change = {}
      change[field] = null
      orderFile.saveSettings(tiles[i].key, change)
      return
    }
  }

  // Where a dragged tile was dropped (LayoutModel.dropTarget): persist and
  // apply it; the tiles follow once the live layout has moved.
  function dropTile(from, target, dx) {
    if (!tiles[from]) return
    if (tiles[from].virtual) {
      saveLayout(LayoutModel.applyVirtualDrop(orderFile.layout, tiles[from].key, target, rowKeys()))
      return
    }
    var tile = tiles[from]
    if (!tile || !target) return
    if (target.on) {
      for (var i = 0; i < tiles.length; i++) {
        if (tiles[i].key === target.on && tiles[i].virtual) {
          var base = baseKey(target.on)
          if (!base || base === tile.key) return
          target = { side: target.side, on: base }
          break
        }
      }
    }
    if (target.side === "row")
      saveLayout(LayoutModel.withRowPosition(orderFile.layout, tile.key, rowKeys(), target.index))
    else
      saveLayout(LayoutModel.withStacked(orderFile.layout, tile.key, target.on, target.side))
  }

  function saveLayout(layout) {
    orderFile.saveLayout(layout)
  }

  spacing: Style.space(10)

  onActiveChanged: {
    grabbedKey = ""
    if (!active) {
      propertiesOutput = ""
      identifyOutputs = []
    }
    if (active) {
      selectedIndex = 0
      refresh()
    }
  }
  onFocusedChanged: if (!focused) grabbedKey = ""
  onTilesChanged: {
    if (selectedIndex > tiles.length - 1) selectedIndex = Math.max(0, tiles.length - 1)
  }
  // The cursor stays on the picked-up tile as it moves.
  onGrabbedIndexChanged: if (grabbedIndex >= 0) selectedIndex = grabbedIndex

  Component.onCompleted: refresh()

  Process {
    id: monitorsProc
    // "all" so a laptop screen turned off in external-only mode is still known.
    command: ["hyprctl", "monitors", "all", "-j"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var monitors = []
        try { monitors = JSON.parse(String(text || "[]")) } catch (e) { monitors = [] }
        root.monitors = monitors
        var layout = LayoutModel.migrateLayoutOrder(orderFile.layout, monitors)
        if (JSON.stringify(layout.order) !== JSON.stringify(orderFile.layout.order || []))
          orderFile.saveLayout(layout)
        root.tiles = LayoutModel.tilesFromMonitors(
          monitors,
          layout.stack,
          layout.monitors,
          layout.order
        )
      }
    }
  }

  // Saved layout: order and per-monitor settings. Kept in memory so
  // remembered-but-unplugged monitors survive a save made while they are away.
  FileView {
    id: orderFile
    path: root.orderPath
    atomicWrites: true
    printErrors: false
    // The service and hand edits change the file too; stay in step so the
    // buttons show, and later saves build on, what is really saved.
    watchChanges: true
    onFileChanged: reload()

    property var layout: ({ order: [], monitors: {} })

    onLoaded: layout = LayoutModel.parseLayout(text())
    onLoadFailed: layout = { order: [], monitors: {} }

    function saveLayout(next) {
      layout = next
      setText(LayoutModel.serializeLayout(layout))
      root.tiles = LayoutModel.tilesFromMonitors(
        root.monitors, layout.stack, layout.monitors, layout.order)
      applier.apply(false, next)
    }

    // Service.qml sees the change and carries the mode out.
    function saveExternalMode(mode) {
      layout = LayoutModel.withExternalMode(layout, mode)
      setText(LayoutModel.serializeLayout(layout))
    }

    // Already live (tried in the properties window), so only saved here.
    function saveSettings(key, settings) {
      layout = LayoutModel.withMonitorSettings(layout, key, settings)
      setText(LayoutModel.serializeLayout(layout))
    }
  }

  MonitorProperties {
    id: properties
    bar: root.bar
    hostPanel: root.panel
    miracast: root.miracast
    open: root.active && root.propertiesTile !== null
    monitor: {
      var tile = root.propertiesTile
      if (!tile) return null
      for (var i = 0; i < root.monitors.length; i++)
        if (root.monitors[i].name === tile.name) return root.monitors[i]
      return null
    }
    savedSettings: root.propertiesTile ? (orderFile.layout.monitors[root.propertiesTile.key] || {}) : ({})
    onCloseRequested: root.propertiesOutput = ""
    // A new mode, scale or rotation changes the tile's size: re-pack the row
    // without restoring saved settings over the change being tried.
    onSettingsApplied: applier.apply(true)
    onKept: function(settings) {
      if (root.propertiesTile) orderFile.saveSettings(root.propertiesTile.key, settings)
    }
  }

  LayoutApplier {
    id: applier
    orderPath: root.orderPath
    onApplied: root.refresh()
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!root.active || !event || !event.name) return
      var name = String(event.name)
      if (name.indexOf("monitor") === 0 || name === "configreloaded" || name === "focusedmon")
        refreshDebounce.restart()
    }
  }

  Timer {
    id: refreshDebounce
    interval: 350
    repeat: false
    onTriggered: root.refresh()
  }

  PanelSectionHeader {
    text: "DISPLAY SETTINGS"
    foreground: root.bar.foreground
    fontFamily: root.bar.fontFamily
  }

  CursorSurface {
    id: row
    width: parent.width
    // Taller once a display stands above or below another.
    height: (canvas.stacked || root.reorderable) ? Style.space(170) : Style.space(110)
    hasCursor: root.cursorActive && root.focused
    foreground: root.bar.foreground
    outline: true

    Item {
      id: canvas
      anchors.fill: parent
      anchors.margins: Style.space(10)

      readonly property var tiles: root.tiles
      readonly property bool stacked: tiles.some(function(tile) { return tile.stacked })
      // Gap drawn between touching displays.
      readonly property real gap: Style.space(6)
      // Bounding box of the live layout, in logical pixels.
      readonly property var bounds: {
        var box = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity }
        for (var i = 0; i < tiles.length; i++) {
          box.left = Math.min(box.left, tiles[i].x)
          box.top = Math.min(box.top, tiles[i].y)
          box.right = Math.max(box.right, tiles[i].x + tiles[i].w)
          box.bottom = Math.max(box.bottom, tiles[i].y + tiles[i].h)
        }
        return tiles.length ? box : { left: 0, top: 0, right: 0, bottom: 0 }
      }
      // Preview pixels per logical monitor pixel, fitting the whole layout.
      readonly property real unit: bounds.right > bounds.left && bounds.bottom > bounds.top
        ? Math.min(width / (bounds.right - bounds.left), height / (bounds.bottom - bounds.top))
        : 0
      readonly property real groupLeft: (width - (bounds.right - bounds.left) * unit) / 2
      readonly property real groupTop: (height - (bounds.bottom - bounds.top) * unit) / 2

      // Tile being dragged (-1 = none) and by how much. Cleared on release,
      // so tiles always rest where the live layout puts them.
      property int dragIndex: -1
      property real dragX: 0
      property real dragY: 0

      // Resting rectangle of a tile, inset by half the gap on each side.
      function rest(index) {
        var tile = tiles[index]
        return {
          key: tile.key,
          stacked: tile.stacked,
          virtual: !!tile.virtual,
          internal: !!tile.internal,
          left: groupLeft + (tile.x - bounds.left) * unit + gap / 2,
          top: groupTop + (tile.y - bounds.top) * unit + gap / 2,
          width: Math.max(1, tile.w * unit - gap),
          height: Math.max(1, tile.h * unit - gap)
        }
      }

      function target(from, dx, dy) {
        var rects = []
        for (var i = 0; i < tiles.length; i++) rects.push(rest(i))
        return LayoutModel.dropTarget(rects, from, dx, dy)
      }

      // Where the tile being dragged would land, for the edge marker.
      readonly property var dropPreview: dragIndex >= 0 ? target(dragIndex, dragX, dragY) : null

      // Accent line on a neighbour: above/below that tile, or left/right of
      // the insertion edge among remaining row tiles.
      function dropSideFor(tileIndex) {
        var p = dropPreview
        if (!p) return ""
        if ((p.side === "above" || p.side === "below") && tiles[tileIndex] && p.on === tiles[tileIndex].key)
          return p.side
        if (p.side !== "row" || dragIndex < 0) return ""
        var remaining = []
        for (var i = 0; i < tiles.length; i++) {
          if (i === dragIndex || tiles[i].stacked) continue
          remaining.push(i)
        }
        if (!remaining.length) return ""
        var at = p.index
        if (at <= 0) return remaining[0] === tileIndex ? "left" : ""
        if (at >= remaining.length) return remaining[remaining.length - 1] === tileIndex ? "right" : ""
        if (remaining[at - 1] === tileIndex) return "right"
        if (remaining[at] === tileIndex) return "left"
        return ""
      }

      function finishDrag() {
        var from = dragIndex
        var dx = dragX
        var dy = dragY
        dragIndex = -1
        dragX = 0
        dragY = 0
        if (from < 0 || (Math.abs(dx) < 2 && Math.abs(dy) < 2)) return
        root.dropTile(from, target(from, dx, dy), dx)
      }

      Repeater {
        model: canvas.tiles

        ScreenTile {
          id: screenTile
          required property var modelData
          required property int index

          readonly property var restRect: canvas.rest(index)
          readonly property bool dragged: canvas.dragIndex === index

          x: restRect.left + (dragged ? canvas.dragX : 0)
          y: restRect.top + (dragged ? canvas.dragY : 0)
          z: dragged ? 2 : 0
          width: restRect.width
          height: restRect.height
          icon: modelData.virtual ? "󰖩" : (modelData.internal ? "󰌢" : "󰍹")
          label: modelData.label
          number: index + 1
          highlighted: modelData.focused
          grabbed: dragged || root.grabbedIndex === index
          hasCursor: root.cursorActive && root.focused && root.selectedIndex === index
          dropSide: canvas.dropSideFor(index)

          MouseArea {
            anchors.fill: parent
            // The panel scrolls inside a Flickable; without this it can steal
            // the gesture and swallow the release.
            preventStealing: true
            hoverEnabled: true
            cursorShape: !root.reorderable ? Qt.PointingHandCursor
              : pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor

            property point pressAt: Qt.point(0, 0)

            onContainsMouseChanged: if (containsMouse && !pressed) {
              root.selectedIndex = screenTile.index
              root.focusRequested()
            }
            onPressed: function(mouse) {
              if (!root.reorderable) return
              pressAt = mapToItem(canvas, mouse.x, mouse.y)
              root.grabbedKey = ""
              canvas.dragX = 0
              canvas.dragY = 0
              canvas.dragIndex = screenTile.index
            }
            onPositionChanged: function(mouse) {
              if (!pressed || canvas.dragIndex !== screenTile.index) return
              var at = mapToItem(canvas, mouse.x, mouse.y)
              var r = screenTile.restRect
              // Keep the tile's center inside the preview. The tile itself may
              // stick out, or a display that fills the preview's height could
              // never reach the bottom or top edge of another to stack there.
              canvas.dragX = Math.max(-r.left - r.width / 2,
                Math.min(canvas.width - r.left - r.width / 2, at.x - pressAt.x))
              canvas.dragY = Math.max(-r.top - r.height,
                Math.min(canvas.height - r.top, at.y - pressAt.y))
            }
            onReleased: canvas.finishDrag()
            onDoubleClicked: {
              root.propertiesOutput = screenTile.modelData.name
            }
            onCanceled: {
              canvas.dragIndex = -1
              canvas.dragX = 0
              canvas.dragY = 0
            }
          }
        }
      }
    }
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(hint.implicitHeight, identifyButton.implicitHeight)

    Text {
      id: hint
      textFormat: Text.PlainText
      text: root.grabbedIndex >= 0 ? "H/J/K/L TO MOVE · ENTER TO DROP"
        : root.cursorActive && root.focused
          ? (root.reorderable ? "ENTER TO PICK UP · I FOR SETTINGS" : "ENTER FOR SETTINGS")
        : root.reorderable ? "DRAG · DOUBLE-CLICK FOR SETTINGS" : "DOUBLE-CLICK FOR SETTINGS"
      color: Qt.darker(root.bar.foreground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      elide: Text.ElideRight
      anchors.left: parent.left
      anchors.right: identifyButton.left
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
    }

    Row {
      id: identifyButton
      spacing: Style.spacing.xs
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter

      Button {
        text: "Settings"
        fontSize: Style.font.caption
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        horizontalPadding: Style.spacing.md
        verticalPadding: Style.spacing.controlPaddingY
        bordered: true
        enabled: root.tiles.length > 0
        onClicked: {
          var tile = root.tiles[root.selectedIndex] || root.tiles.filter(function(t) { return t.focused })[0] || root.tiles[0]
          if (tile) root.propertiesOutput = tile.name
        }
      }

      Button {
        text: "Identify"
        fontSize: Style.font.caption
        foreground: root.bar.foreground
        fontFamily: root.bar.fontFamily
        horizontalPadding: Style.spacing.md
        verticalPadding: Style.spacing.controlPaddingY
        bordered: true
        active: root.identifyOutputs.length > 0
        onClicked: root.identify()
      }
    }
  }

  // Laptop screen while an external display is connected, like Win+P.
  Column {
    visible: root.hasInternal
    width: parent.width
    spacing: Style.space(10)
    topPadding: Style.space(4)

    PanelSectionHeader {
      text: "WITH AN EXTERNAL DISPLAY"
      foreground: root.bar.foreground
      fontFamily: root.bar.fontFamily
    }

    Grid {
      id: modeRow
      width: parent.width
      columns: 3
      spacing: Style.spacing.xs

      readonly property real cellWidth: (width - spacing * (columns - 1)) / columns

      Repeater {
        model: [
          { value: "extend", label: "Extend" },
          { value: "external-only", label: "External only" },
          { value: "mirror", label: "Mirror" }
        ]

        Button {
          required property var modelData
          width: modeRow.cellWidth
          text: modelData.label
          fontSize: Style.font.caption
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.controlPaddingY
          bordered: true
          active: orderFile.layout.withExternal === modelData.value
          onClicked: root.setExternalMode(modelData.value)
        }
      }
    }
  }

  Column {
    visible: root.miracast && root.miracast.active
    width: parent.width
    spacing: Style.space(10)
    topPadding: Style.space(4)

    PanelSectionHeader {
      text: "WITH A MIRACAST DISPLAY"
      foreground: root.bar.foreground
      fontFamily: root.bar.fontFamily
    }

    Grid {
      id: miracastModeRow
      width: parent.width
      columns: 2
      spacing: Style.spacing.xs

      readonly property real cellWidth: (width - spacing * (columns - 1)) / columns

      Repeater {
        model: [
          { value: "extend", label: "Extend" },
          { value: "mirror", label: "Mirror" }
        ]

        Button {
          required property var modelData
          width: miracastModeRow.cellWidth
          text: modelData.label
          fontSize: Style.font.caption
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          horizontalPadding: Style.spacing.sm
          verticalPadding: Style.spacing.controlPaddingY
          bordered: true
          active: root.miracast && root.miracast.mode === modelData.value
          onClicked: if (root.miracast) root.miracast.setMode(modelData.value)
        }
      }
    }
  }

  // Numbers the displays on their screens: all of them for a moment after
  // Identify, and the one whose settings window is open.
  IdentifyOverlay {
    foreground: root.bar.foreground
    fontFamily: root.bar.fontFamily
    entries: {
      var list = []
      for (var i = 0; i < root.tiles.length; i++) {
        var tile = root.tiles[i]
        if (root.identifyOutputs.indexOf(tile.name) === -1 && tile.name !== root.propertiesOutput) continue
        list.push({ output: tile.name, number: i + 1, label: tile.internal ? "Built-in display" : tile.label })
      }
      return root.active ? list : []
    }
  }

  Process {
    id: modeReset
    command: {
      var steps = LayoutModel.extendCommands()
      return ["bash", "-c", "\"$1\" \"$2\"; \"$3\" \"$4\"", "_"]
        .concat(steps[0]).concat(steps[1])
    }
    stdout: StdioCollector { waitForEnd: true }
    onRunningChanged: if (!running) root.refresh()
  }

  Timer {
    id: identifyTimer
    interval: 3000
    onTriggered: root.identifyOutputs = []
  }

  // One display in the preview. highlighted = focused display (accent border);
  // grabbed = being dragged or picked up with Enter (filled); hasCursor =
  // keyboard cursor (thicker outline).
  component ScreenTile: Rectangle {
    id: tile
    property string icon: ""
    property string label: ""
    property int number: 0
    // "above" / "below" / "left" / "right": the dragged display would land here.
    property string dropSide: ""
    property bool highlighted: false
    property bool grabbed: false
    property bool hasCursor: false

    readonly property color faint: Qt.rgba(root.bar.foreground.r, root.bar.foreground.g, root.bar.foreground.b, 0.06)
    readonly property color line: Qt.rgba(root.bar.foreground.r, root.bar.foreground.g, root.bar.foreground.b, 0.35)

    radius: Style.cornerRadius
    color: grabbed ? Style.selectedFillFor(root.bar.foreground, Color.accent) : faint
    border.width: hasCursor ? 2 : 1
    border.color: hasCursor ? root.bar.foreground : (highlighted ? Color.accent : line)

    Rectangle {
      visible: tile.dropSide === "above" || tile.dropSide === "below"
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: tile.dropSide === "above" ? parent.top : undefined
      anchors.bottom: tile.dropSide === "below" ? parent.bottom : undefined
      height: Math.max(2, Style.space(3))
      radius: height / 2
      color: Color.accent
    }

    Rectangle {
      visible: tile.dropSide === "left" || tile.dropSide === "right"
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      anchors.left: tile.dropSide === "left" ? parent.left : undefined
      anchors.right: tile.dropSide === "right" ? parent.right : undefined
      width: Math.max(2, Style.space(3))
      radius: width / 2
      color: Color.accent
    }

    // Matches the number Identify shows on the screen.
    Text {
      textFormat: Text.PlainText
      text: tile.number > 0 ? String(tile.number) : ""
      color: Qt.darker(root.bar.foreground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      anchors.left: parent.left
      anchors.top: parent.top
      anchors.leftMargin: Style.space(6)
      anchors.topMargin: Style.space(4)
    }

    Column {
      anchors.centerIn: parent
      width: parent.width - Style.space(6)
      spacing: Style.space(2)

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: tile.icon
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.title
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        textFormat: Text.PlainText
        text: tile.label
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }
}
