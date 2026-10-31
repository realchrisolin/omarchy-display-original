import QtQuick
import Quickshell
import Quickshell.Io
import "LayoutModel.js" as LayoutModel

// Reads the saved layout and the live monitors, restores each monitor's saved
// settings (mode, scale, rotation, adaptive sync) where they have drifted, then
// moves every monitor into place with position-only `hl.monitor` rules in a
// single `hyprctl eval`:
// first past the right edge of the current and the target layout, then to
// the target, so no intermediate state overlaps (see LayoutModel.positionsToLua).
// Does nothing when every monitor is already where it belongs.
QtObject {
  id: root

  required property string orderPath
  readonly property string reloadLuaPath: Quickshell.env("HOME") + "/.config/hypr/monitors-layout.lua"
  // Also carry out the saved laptop-screen mode (withExternal) through
  // Omarchy's commands. Only the service does, so the panel's applier cannot
  // run them a second time in parallel.
  property bool manageExternalMode: false

  // Emitted after each pass, whether or not anything had to move.
  signal applied()

  property bool _pending: false
  property bool _pendingSettings: false
  // Settings are restored at most once per pass, so a mode Hyprland refuses
  // cannot keep the applier looping.
  property bool _settingsTried: false
  // Outputs this applier has positioned, so unplugged ones can be parked.
  property var _knownOutputs: []
  property var _layout: ({})
  property var _monitors: []
  property string _pendingLua: ""
  property string _pendingJson: ""
  // Arrangement saveLayout races FileView setText; cat would see the old row
  // and persist it back, wiping stack.
  property var _forcedLayout: null

  // positionsOnly: leave monitor settings alone, e.g. while a change made in
  // the properties window waits to be kept or reverted.
  function apply(positionsOnly, layoutOverride) {
    if (layoutOverride)
      root._forcedLayout = layoutOverride
    if (readProc.running || evalProc.running || modeProc.running) {
      _pending = true
      _pendingSettings = _pendingSettings || !positionsOnly
      return
    }
    _pending = false
    _pendingSettings = false
    _settingsTried = !!positionsOnly
    readProc.running = true
  }

  function _finish() {
    root.applied()
    if (_pending) apply(!_pendingSettings)
  }

  // Order file and monitor list in one process, split by an ASCII record separator.
  property Process readProc: Process {
    command: ["bash", "-c", "cat -- \"$1\" 2>/dev/null; printf '\\036'; hyprctl monitors all -j", "_", root.orderPath]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parts = String(text || "").split("\u001e")
        var fileLayout = LayoutModel.parseLayout(parts[0])
        var layout = root._forcedLayout || fileLayout
        root._forcedLayout = null
        var monitors = []
        try { monitors = JSON.parse(parts[1] || "[]") } catch (e) { monitors = [] }

        // The laptop-screen mode goes first: Omarchy's command reloads the
        // config, and the reload brings the service back here.
        var modeCommand = root.manageExternalMode && !root._settingsTried
          ? LayoutModel.externalModeCommand(monitors, layout.withExternal) : null
        if (modeCommand) {
          root._settingsTried = true
          root.modeProc.command = modeCommand
          root.modeProc.running = true
          return
        }

        // Settings change logical sizes, so positions are computed from a
        // fresh read once they have been restored.
        var drifted = root._settingsTried ? [] : LayoutModel.pendingSettings(monitors, layout)
        root._settingsTried = true
        if (drifted.length > 0) {
          root.evalProc.rereadAfter = true
          root.evalProc.command = ["hyprctl", "eval", LayoutModel.settingsToLua(drifted)]
          root.evalProc.running = true
          return
        }

        layout = LayoutModel.migrateLayoutOrder(layout, monitors)
        root._layout = layout
        root._monitors = monitors
        var positions = LayoutModel.computePositions(monitors, layout.order, layout.stack, layout.monitors)
        // Only unplugged outputs are parked; a connected but disabled one (the
        // laptop screen in external-only mode) is left alone.
        var connected = monitors.map(function(monitor) { return String(monitor.name) })
        var parked = LayoutModel.parkedOutputs(root._knownOutputs, positions).filter(function(name) {
          return connected.indexOf(name) === -1
        })
        var known = parked.slice()
        positions.forEach(function(p) { known.push(p.name) })
        root._knownOutputs = known

        var anyChanged = positions.some(function(p) {
          return p.changed && !LayoutModel.isVirtualHead({ name: p.name })
        })
        if (!anyChanged && LayoutModel.packableOverlap(monitors))
          anyChanged = true
        if (!anyChanged) {
          var same = LayoutModel.serializeLayout(layout) === LayoutModel.serializeLayout(fileLayout)
          root._persistReloadLua(monitors, layout, !same)
          root._finish()
          return
        }
        var staging = LayoutModel.stagingX(monitors, positions, layout.monitors)
        root.evalProc.persistAfter = true
        root.evalProc.command = ["hyprctl", "eval", LayoutModel.positionsToLua(positions, staging, parked)]
        root.evalProc.running = true
      }
    }
  }

  property Process modeProc: Process {
    stdout: StdioCollector { waitForEnd: true }
    onRunningChanged: if (!running) root._finish()
  }

  function _persistReloadLua(monitors, layout, writeJson) {
    root._pendingJson = writeJson === false ? "" : LayoutModel.serializeLayout(layout)
    root._pendingLua = LayoutModel.physicalReloadLua(monitors, layout)
    root._flushLua()
  }

  function _flushLua() {
    if (luaPersist.running) return
    var json = root._pendingJson
    var lua = root._pendingLua
    if (!json && !lua) return
    root._pendingJson = ""
    root._pendingLua = ""
    luaPersist.command = ["python3", "-c",
      "import base64, fcntl, sys\n"
      + "from pathlib import Path\n"
      + "def write(path, raw):\n"
      + "    if not raw: return\n"
      + "    p = Path(path)\n"
      + "    t = base64.b64decode(raw).decode()\n"
      + "    p.parent.mkdir(parents=True, exist_ok=True)\n"
      + "    lock = open(str(p) + '.lock', 'a')\n"
      + "    fcntl.flock(lock, fcntl.LOCK_EX)\n"
      + "    try:\n"
      + "        if not p.exists() or p.read_text() != t:\n"
      + "            p.write_text(t)\n"
      + "    finally:\n"
      + "        fcntl.flock(lock, fcntl.LOCK_UN)\n"
      + "        lock.close()\n"
      + "write(sys.argv[1], sys.argv[3])\n"
      + "write(sys.argv[2], sys.argv[4])\n",
      root.orderPath, root.reloadLuaPath, Qt.btoa(json), Qt.btoa(lua)]
    luaPersist.running = true
  }

  property Process orderPersist: Process {
    stdout: StdioCollector { waitForEnd: true }
  }
  property Process luaPersist: Process {
    stdout: StdioCollector { waitForEnd: true }
    onRunningChanged: if (!running) root._flushLua()
  }

  property Process evalProc: Process {
    property bool rereadAfter: false
    property bool persistAfter: false
    stdout: StdioCollector { waitForEnd: true }
    onRunningChanged: {
      if (running) return
      if (rereadAfter) {
        rereadAfter = false
        root.readProc.running = true
      } else {
        if (persistAfter) {
          persistAfter = false
          root._persistReloadLua(root._monitors, root._layout)
        }
        root._finish()
      }
    }
  }
}
