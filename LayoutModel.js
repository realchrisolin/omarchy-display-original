// Pure layout logic shared by Service.qml, Panel.qml and the Node tests.
//
// A layout is a left-to-right order of monitor keys (the row), plus monitors
// stacked above or below another one (`stack`), centered on it. A key is the monitor's
// description (make, model and serial, stable across ports) or its output
// name when the description is empty or shared by another connected monitor
// (identical models that report no serial number). Monitors are placed in a single top-aligned row with
// no gaps, using their logical (post-scale, post-rotation) widths.

var INTERNAL_OUTPUT = /^(eDP|LVDS|DSI)-/

// Saved settings format: "3440x1440@99.98" (see modeString/parseMode).
var SETTINGS_MODE_RE = /^\d+x\d+@\d+(\.\d+)?$/

function description(monitor) {
  return String((monitor && monitor.description) || "").trim()
}

// Descriptions that more than one of `monitors` reports.
function sharedDescriptions(monitors) {
  var seen = {}
  var shared = {}
  for (var i = 0; i < (monitors || []).length; i++) {
    var d = description(monitors[i])
    if (d === "") continue
    if (seen[d]) shared[d] = true
    seen[d] = true
  }
  return shared
}

// `shared` (from sharedDescriptions) lists descriptions that cannot tell
// monitors apart; those monitors are keyed by output name instead.
function monitorKey(monitor, shared) {
  var d = description(monitor)
  if (d !== "" && !(shared && shared[d])) return d
  return String((monitor && monitor.name) || "")
}

function isInternal(monitor) {
  return INTERNAL_OUTPUT.test(String((monitor && monitor.name) || ""))
}

// Miracast Extend heads (Hyprland headless). Packed in computePositions.
// hl.monitor / lua skip them. miracast-ctl parks at -12000 and places at packed x,y.
var VIRTUAL_OUTPUT = /^(HEADLESS|persistent-miracast|Miracast)/

function isVirtualHead(monitor) {
  if (!monitor) return false
  if (monitor.miracast) return true
  var name = String(monitor.name || "")
  if (VIRTUAL_OUTPUT.test(name)) return true
  if (name.indexOf("HEADLESS-") === 0) return true
  return false
}

// miracast-ctl parks unused Extend heads at -12000. Those must not pull the
// arrangement preview's bounding box off to the left.
function isParkedVirtual(monitor) {
  if (!isVirtualHead(monitor)) return false
  return (Number(monitor.x) || 0) <= -10000
}

// Physical arrangeable outputs, plus the Miracast HEADLESS head (parked or
// live) so DISPLAY SETTINGS can place it. Layout apply still uses isArrangeable
// only; place-virtual-head owns the real output.
function isPreviewable(monitor) {
  if (isArrangeable(monitor)) return true
  if (!isVirtualHead(monitor)) return false
  var w = Number(monitor.width) || 0
  var h = Number(monitor.height) || 0
  return w > 0 && h > 0
}

// Hyprland on kenya (ICC fork) reports disabled=true on the focused, DPMS-on
// eDP. Trust size + DPMS/focus; only skip a disabled output that is not presenting.
function isPresenting(monitor) {
  if (!monitor) return false
  var w = Number(monitor.width) || 0
  var h = Number(monitor.height) || 0
  if (w <= 0 || h <= 0) return false
  if (monitor.focused) return true
  if (monitor.dpmsStatus === true) return true
  if (monitor.disabled === true) return false
  return true
}

// Off, mirrored, and Miracast virtual heads take no space in the layout.
function isArrangeable(monitor) {
  if (!isPresenting(monitor)) return false
  if (isVirtualHead(monitor)) return false
  var mirrorOf = monitor.mirrorOf
  return mirrorOf === undefined || mirrorOf === null || mirrorOf === "" || mirrorOf === "none"
}

function isPackable(monitor) {
  return isArrangeable(monitor) || (isVirtualHead(monitor) && isPreviewable(monitor))
}

function logicalSize(monitor) {
  var scale = Number(monitor.scale) > 0 ? Number(monitor.scale) : 1
  // Transforms 1/3/5/7 rotate by 90° or 270°: swap the axes.
  var rotated = (Number(monitor.transform) || 0) % 2 === 1
  var width = Number(rotated ? monitor.height : monitor.width) || 0
  var height = Number(rotated ? monitor.width : monitor.height) || 0
  return { w: Math.round(width / scale), h: Math.round(height / scale) }
}

// Copy of `monitor` with JSON scale/transform when those fields are saved, so
// packing uses intended logical size even if hyprctl still has the old scale.
function withSavedGeometry(monitor, shared, monitorSettings) {
  var saved = (monitorSettings || {})[monitorKey(monitor, shared)]
    || (monitorSettings || {})[String(monitor.name || "")]
    || {}
  if (saved.scale === undefined && saved.transform === undefined) return monitor
  var copy = {}
  for (var k in monitor) copy[k] = monitor[k]
  if (saved.scale !== undefined) copy.scale = saved.scale
  if (saved.transform !== undefined) copy.transform = saved.transform
  return copy
}

// Short tile label: "Built-in" for the laptop panel, otherwise the model
// ("U34V5C", "DELL P2419H"), falling back to the description's first words
// and then to the output name.
function tileLabel(monitor) {
  if (isInternal(monitor)) return "Built-in"
  if (isVirtualHead(monitor)) {
    var virtModel = String(monitor.model || "").trim()
    if (virtModel !== "") return virtModel
    var virtWords = description(monitor).split(/\s+/).filter(function(word) { return word !== "" })
    if (virtWords.length && virtWords[0] !== String(monitor.name || ""))
      return virtWords.slice(0, 2).join(" ")
    return "Miracast"
  }
  var model = String(monitor.model || "").trim()
  if (model !== "") return model
  var words = description(monitor).split(/\s+/).filter(function(word) { return word !== "" })
  return words.length ? words.slice(0, 2).join(" ") : String(monitor.name || "")
}

// Keeps only the fields of a per-monitor settings entry that are valid,
// normalizing scale to at most 2 decimals. Returns {} for garbage input.
function cleanSettings(obj) {
  var result = {}
  if (!obj || typeof obj !== "object") return result

  if (typeof obj.mode === "string" && SETTINGS_MODE_RE.test(obj.mode)) result.mode = obj.mode

  if (obj.scale !== undefined && obj.scale !== null) {
    var scale = Number(obj.scale)
    if (isFinite(scale) && scale > 0 && scale <= 10) result.scale = Math.round(scale * 100) / 100
  }

  if (obj.transform !== undefined && obj.transform !== null) {
    var transform = Number(obj.transform)
    if (Number.isInteger(transform) && transform >= 0 && transform <= 7) result.transform = transform
  }

  if (obj.vrr !== undefined && obj.vrr !== null) {
    var vrr = Number(obj.vrr)
    if (Number.isInteger(vrr) && vrr >= 0 && vrr <= 2) result.vrr = vrr
  }

  return result
}

// `text` holds `{ order: [...], monitors: { <key>: { mode, scale, transform, vrr } } }`.
// Tolerates missing fields and invalid JSON, and drops monitor entries that
// clean to nothing.
function parseLayout(text) {
  var data = null
  try {
    data = JSON.parse(String(text || ""))
  } catch (e) {
    data = null
  }

  var order = data && Array.isArray(data.order) ? data.order : []
  order = order.filter(function(key) { return typeof key === "string" && key !== "" })

  var monitors = {}
  var rawMonitors = data && data.monitors && typeof data.monitors === "object" ? data.monitors : {}
  for (var key in rawMonitors) {
    if (!Object.prototype.hasOwnProperty.call(rawMonitors, key)) continue
    var cleaned = cleanSettings(rawMonitors[key])
    if (Object.keys(cleaned).length > 0) monitors[key] = cleaned
  }

  return {
    order: order,
    monitors: monitors,
    withExternal: cleanExternalMode(data && data.withExternal),
    stack: cleanStack(data && data.stack)
  }
}

function parseOrder(text) {
  return parseLayout(text).order
}

// Omits `monitors` entirely when empty, so files saved before per-monitor
// settings existed stay byte-identical.
function serializeLayout(layout) {
  var order = (layout && layout.order) || []
  var monitors = (layout && layout.monitors) || {}
  var data = { order: order }
  if (Object.keys(monitors).length > 0) data.monitors = monitors
  var mode = cleanExternalMode(layout && layout.withExternal)
  if (mode !== "extend") data.withExternal = mode
  var stack = cleanStack(layout && layout.stack)
  if (Object.keys(stack).length > 0) data.stack = stack
  return JSON.stringify(data, null, 2) + "\n"
}

function serializeOrder(order) {
  return serializeLayout({ order: order })
}

// New layout with `settings` merged into `layout.monitors[key]`, without
// mutating `layout`. A field set to `null` removes that field; an entry left
// empty is dropped entirely. The result is run through cleanSettings.
function withMonitorSettings(layout, key, settings) {
  var monitors = {}
  var sourceMonitors = (layout && layout.monitors) || {}
  for (var k in sourceMonitors) {
    if (Object.prototype.hasOwnProperty.call(sourceMonitors, k)) monitors[k] = sourceMonitors[k]
  }

  var merged = {}
  var existing = monitors[key] || {}
  for (var field in existing) {
    if (Object.prototype.hasOwnProperty.call(existing, field)) merged[field] = existing[field]
  }
  var changes = settings || {}
  for (var f in changes) {
    if (!Object.prototype.hasOwnProperty.call(changes, f)) continue
    if (changes[f] === null) delete merged[f]
    else merged[f] = changes[f]
  }

  var cleaned = cleanSettings(merged)
  if (Object.keys(cleaned).length > 0) monitors[key] = cleaned
  else delete monitors[key]

  var copy = copyLayout(layout)
  copy.monitors = monitors
  return copy
}

// What the laptop screen does while an external display is connected, like
// Windows' Win+P: "extend" (both in use, the default), "external-only" (the
// laptop screen is turned off) or "mirror" (the external shows the laptop
// screen).
var EXTERNAL_MODES = ["extend", "external-only", "mirror"]

function cleanExternalMode(mode) {
  return EXTERNAL_MODES.indexOf(mode) === -1 ? "extend" : mode
}

// New layout with `order` replaced (merged with the remembered order, see
// mergeOrder) and everything else kept.
function withOrder(layout, keys) {
  var copy = copyLayout(layout)
  copy.order = mergeOrder(keys, (layout && layout.order) || [])
  return copy
}

function withExternalMode(layout, mode) {
  var copy = copyLayout(layout)
  copy.withExternal = cleanExternalMode(mode)
  return copy
}

// True while Miracast is in P2P/RTSP handshake. Layout must not modeset eDP
// in that window (GO Neg + eDP place has locked i915 on kenya).
// connecting.lock covers the gap before status.json says connecting; once
// streaming, layout may apply to physical monitors again.
function shouldHoldLayout(status, lockPresent) {
  var phase = String((status && status.phase) || "").toLowerCase()
  if (phase === "connecting" || phase === "dhcp" || phase === "rtsp") return true
  if (lockPresent && phase !== "streaming") return true
  return false
}

// The next Omarchy command that brings `monitors` (`hyprctl monitors all -j`)
// in line with `mode`, or null when nothing has to change. One step at a
// time: each command reloads the config, which brings the service back here
// for the next one (external-only while mirroring first ends the mirror).
// Only acts while a laptop screen and an enabled external display are both
// connected; Omarchy itself turns the laptop screen back on and ends
// mirroring when the last external display goes away. "extend" never acts on
// its own, so a laptop screen turned off by other means stays off.
function externalModeCommand(monitors, mode) {
  var list = monitors || []
  var internal = null
  var externals = []
  for (var i = 0; i < list.length; i++) {
    if (isInternal(list[i])) {
      if (!internal) internal = list[i]
    } else if (!list[i].disabled && !isVirtualHead(list[i])) {
      externals.push(list[i])
    }
  }
  if (!internal || externals.length === 0) return null

  // hyprctl reports the mirrored output by id ("0"); accept its name too.
  var mirrored = externals.some(function(monitor) {
    var of = String(monitor.mirrorOf)
    return of === String(internal.name) || (internal.id !== undefined && of === String(internal.id))
  })
  if (mode === "external-only" && mirrored)
    return ["omarchy-hyprland-monitor-internal-mirror", "off"]
  if (mode === "external-only" && !internal.disabled)
    return ["omarchy-hyprland-monitor-internal", "off"]
  if (mode === "mirror" && !mirrored)
    return ["omarchy-hyprland-monitor-internal-mirror", "on"]
  return null
}

// Commands that undo "external-only" and "mirror" when switching back to
// "extend", which the service leaves alone. Both are no-ops when their state
// is not set.
function extendCommands() {
  return [
    ["omarchy-hyprland-monitor-internal-mirror", "off"],
    ["omarchy-hyprland-monitor-internal", "on"]
  ]
}

// Parses "3440x1440@99.98Hz", "3440x1440@99.98" or "1920x1080" (refresh 0
// when absent). Returns null when `str` does not look like a mode.
function parseMode(str) {
  var match = /^(\d+)x(\d+)(?:@(\d+(?:\.\d+)?)(?:Hz)?)?$/i.exec(String(str || "").trim())
  if (!match) return null
  return {
    width: parseInt(match[1], 10),
    height: parseInt(match[2], 10),
    refresh: match[3] ? parseFloat(match[3]) : 0
  }
}

// At most 2 decimals, trailing zeros trimmed: 60 -> "60", 99.982 -> "99.98".
function formatRefresh(hz) {
  return String(Math.round(Number(hz) * 100) / 100)
}

function modeString(width, height, refresh) {
  return width + "x" + height + "@" + formatRefresh(refresh)
}

// Unique resolutions from hyprctl's available-modes strings ("3072x1920@120.00Hz"),
// sorted by pixel count desc, then width desc (widescreen before ultrawide-tall
// equivalents at the same pixel count).
function resolutionOptions(availableModes) {
  var seen = {}
  var list = []
  for (var i = 0; i < (availableModes || []).length; i++) {
    var parsed = parseMode(availableModes[i])
    if (!parsed) continue
    var value = parsed.width + "x" + parsed.height
    if (seen[value]) continue
    seen[value] = true
    list.push({ value: value, label: parsed.width + " × " + parsed.height, width: parsed.width, height: parsed.height })
  }
  list.sort(function(a, b) {
    var pixelsA = a.width * a.height
    var pixelsB = b.width * b.height
    if (pixelsA !== pixelsB) return pixelsB - pixelsA
    return b.width - a.width
  })
  return list
}

// Refresh rates available for one resolution, deduped by their formatted
// value and sorted highest first.
function refreshOptions(availableModes, width, height) {
  var seen = {}
  var list = []
  for (var i = 0; i < (availableModes || []).length; i++) {
    var parsed = parseMode(availableModes[i])
    if (!parsed || parsed.width !== width || parsed.height !== height) continue
    var value = formatRefresh(parsed.refresh)
    if (seen[value]) continue
    seen[value] = true
    list.push({ value: value, label: value + " Hz" })
  }
  list.sort(function(a, b) { return Number(b.value) - Number(a.value) })
  return list
}

// Current settings of a hyprctl monitor JSON object, in the saved-settings shape.
function liveSettings(monitor) {
  var scale = Number(monitor.scale) > 0 ? Number(monitor.scale) : 1
  return {
    mode: modeString(Number(monitor.width) || 0, Number(monitor.height) || 0, Number(monitor.refreshRate) || 0),
    scale: Math.round(scale * 100) / 100,
    transform: Number(monitor.transform) || 0,
    vrr: monitor.vrr ? 1 : 0
  }
}

// True when every field present in `settings` already holds on the live
// `monitor` (a hyprctl monitor JSON object), so re-applying it would be a
// no-op. vrr 2 (fullscreen-only) always matches: hyprctl's JSON cannot tell
// that state apart from off, and treating it as a mismatch would re-apply
// the rule forever.
function settingsMatch(monitor, settings) {
  if (!settings) return true

  if (settings.mode !== undefined) {
    var parsed = parseMode(settings.mode)
    if (!parsed) return false
    if ((Number(monitor.width) || 0) !== parsed.width) return false
    if ((Number(monitor.height) || 0) !== parsed.height) return false
    if (Math.abs((Number(monitor.refreshRate) || 0) - parsed.refresh) >= 0.05) return false
  }

  if (settings.scale !== undefined) {
    if (Math.abs((Number(monitor.scale) || 0) - Number(settings.scale)) >= 0.005) return false
  }

  if (settings.transform !== undefined) {
    if ((Number(monitor.transform) || 0) !== Number(settings.transform)) return false
  }

  if (settings.vrr !== undefined) {
    if (settings.vrr === 0 && monitor.vrr) return false
    if (settings.vrr === 1 && monitor.vrr !== true) return false
    // vrr === 2: always matches.
  }

  return true
}

// Fields of `settings` the live `monitor` does not show after they were
// applied, i.e. the ones Hyprland refused or replaced. [] when all took.
function rejectedFields(monitor, settings) {
  var fields = ["mode", "scale", "transform", "vrr"]
  return fields.filter(function(field) {
    if (!settings || settings[field] === undefined) return false
    var one = {}
    one[field] = settings[field]
    return !settingsMatch(monitor, one)
  })
}

// hl.monitor({ output = ..., mode = ..., scale = ..., transform = ..., vrr = ... })
// with only the fields present in `settings`, in that fixed order. "" when
// `settings` has none.
function settingsRule(name, settings) {
  settings = settings || {}
  var parts = ["output = " + luaString(name)]
  if (settings.mode !== undefined) parts.push("mode = " + luaString(settings.mode))
  if (settings.scale !== undefined) parts.push("scale = " + settings.scale)
  if (settings.transform !== undefined) parts.push("transform = " + settings.transform)
  if (settings.vrr !== undefined) parts.push("vrr = " + settings.vrr)
  if (parts.length === 1) return ""
  return "hl.monitor({ " + parts.join(", ") + " })"
}

// [{ name, settings }] for connected, non-disabled monitors that have a saved
// settings entry and whose live settings do not already match it. Looked up
// the same way rank() looks up a saved order entry: by monitorKey first,
// falling back to the output name.
function pendingSettings(monitors, layout) {
  var list = (monitors || []).filter(function(monitor) {
    if (!monitor) return false
    if (isArrangeable(monitor)) return true
    return isVirtualHead(monitor) && isPreviewable(monitor)
  })
  var shared = sharedDescriptions(list)
  var monitorSettings = (layout && layout.monitors) || {}
  var result = []
  for (var i = 0; i < list.length; i++) {
    var monitor = list[i]
    var settings = monitorSettings[monitorKey(monitor, shared)]
    if (!settings) settings = monitorSettings[String(monitor.name || "")]
    if (!settings) continue
    if (settingsMatch(monitor, settings)) continue
    result.push({ name: String(monitor.name), settings: settings })
  }
  return result
}

function settingsToLua(pending) {
  return (pending || []).map(function(p) { return settingsRule(p.name, p.settings) }).join("\n")
}

// Merge live arrangeable (non-virtual) settings into layout.monitors so
// scale/rotation survive hyprctl reload. Unplugged keys stay. vrr 2 is kept
// because hyprctl JSON cannot tell fullscreen-only VRR from off.
function snapshotPhysicalSettings(monitors, layout) {
  var list = (monitors || []).filter(isArrangeable)
  var shared = sharedDescriptions(list)
  var monitorsOut = {}
  var source = (layout && layout.monitors) || {}
  for (var k in source) {
    if (Object.prototype.hasOwnProperty.call(source, k)) monitorsOut[k] = source[k]
  }
  for (var i = 0; i < list.length; i++) {
    var m = list[i]
    var key = monitorKey(m, shared)
    var live = liveSettings(m)
    var prev = monitorsOut[key] || {}
    // Never copy live over a saved scale/rotation — after hyprctl reload
    // live is Hyprland defaults until JSON is applied.
    monitorsOut[key] = cleanSettings({
      mode: prev.mode !== undefined ? prev.mode : live.mode,
      scale: prev.scale !== undefined ? prev.scale : live.scale,
      transform: prev.transform !== undefined ? prev.transform : live.transform,
      vrr: prev.vrr !== undefined ? prev.vrr : live.vrr
    })
  }
  return {
    order: (layout && layout.order) || [],
    monitors: monitorsOut,
    withExternal: layout && layout.withExternal,
    stack: layout && layout.stack
  }
}

// hl.monitor rules for physical outputs only, for ~/.config/hypr/monitors-layout.lua.
// hyprctl reload reads this after monitors.lua so DP-2 scale/rotation persist.
function physicalReloadLua(monitors, layout) {
  var list = (monitors || []).filter(isArrangeable)
  var header = [
    "-- Generated by realchrisolin.display from ~/.config/omarchy/monitor-layout.json",
    "-- Physical outputs only. persistent-miracast / HEADLESS* are omitted.",
    ""
  ]
  if (list.length === 0) return header.join("\n") + "-- No physical outputs.\n"
  var positions = computePositions(
    monitors,
    (layout && layout.order) || [],
    (layout && layout.stack) || {},
    (layout && layout.monitors) || {}
  )
  var byName = {}
  for (var p = 0; p < positions.length; p++) byName[positions[p].name] = positions[p]
  var shared = sharedDescriptions(list)
  var saved = (layout && layout.monitors) || {}
  var lines = header.slice()
  for (var i = 0; i < list.length; i++) {
    var m = list[i]
    var key = monitorKey(m, shared)
    var prev = saved[key] || saved[String(m.name || "")] || {}
    var live = liveSettings(m)
    var pos = byName[m.name]
    var parts = ["output = " + luaString(m.name)]
    var mode = prev.mode !== undefined ? prev.mode : live.mode
    if (mode) parts.push("mode = " + luaString(mode))
    if (pos) parts.push("position = " + luaString(pos.x + "x" + pos.y))
    var scale = prev.scale !== undefined ? prev.scale : live.scale
    parts.push("scale = " + scale)
    var transform = prev.transform !== undefined ? prev.transform : live.transform
    parts.push("transform = " + transform)
    var vrr = prev.vrr !== undefined ? prev.vrr : live.vrr
    if (vrr !== undefined) parts.push("vrr = " + vrr)
    lines.push("hl.monitor({ " + parts.join(", ") + " })")
  }
  return lines.join("\n") + "\n"
}

// Screen diagonal in inches, rounded to 1 decimal. 0 when the physical size
// is missing or non-positive (common for VMs and some projectors).
function diagonalInches(physicalWidthMm, physicalHeightMm) {
  var w = Number(physicalWidthMm)
  var h = Number(physicalHeightMm)
  if (!isFinite(w) || !isFinite(h) || w <= 0 || h <= 0) return 0
  var diagonalMm = Math.sqrt(w * w + h * h)
  return Math.round((diagonalMm / 25.4) * 10) / 10
}

// Pixels per inch, rounded to the nearest integer. 0 when unknown.
function pixelDensity(width, height, physicalWidthMm, physicalHeightMm) {
  var diagonal = diagonalInches(physicalWidthMm, physicalHeightMm)
  var w = Number(width)
  var h = Number(height)
  if (diagonal <= 0 || !isFinite(w) || !isFinite(h) || w <= 0 || h <= 0) return 0
  return Math.round(Math.sqrt(w * w + h * h) / diagonal)
}

var ROTATION_LABELS = [
  "Normal", "90°", "180°", "270°",
  "Flipped", "Flipped 90°", "Flipped 180°", "Flipped 270°"
]

function rotationLabel(transform) {
  return ROTATION_LABELS[Number(transform)] || ROTATION_LABELS[0]
}

// Keys placed by the user come first; remembered monitors that are not
// connected right now keep their relative order after them.
// Insert the Miracast head into layout.order once. Default: right of the
// packed hardware row. Ignore leftover extendPosition when USB-C already
// occupies the left of eDP.
function migrateLayoutOrder(layout, monitors) {
  var copy = copyLayout(layout)
  var virt = null
  for (var i = 0; i < (monitors || []).length; i++) {
    if (isVirtualHead(monitors[i]) && isPreviewable(monitors[i])) {
      virt = monitors[i]
      break
    }
  }
  if (!virt) return copy
  var shared = sharedDescriptions((monitors || []).filter(isPackable))
  var key = String(virt.name || "persistent-miracast")
  var order = (copy.order || []).slice()
  if (order.indexOf(key) >= 0) return copy
  copy.order = order.concat([key])
  return copy
}

function mergeOrder(keys, previous) {
  var merged = keys.slice()
  for (var i = 0; i < (previous || []).length; i++) {
    if (merged.indexOf(previous[i]) === -1) merged.push(previous[i])
  }
  return merged
}

function rank(order, monitor, shared) {
  var index = order.indexOf(monitorKey(monitor, shared))
  if (index === -1) index = order.indexOf(String(monitor.name || ""))
  return index
}

// Monitors in the saved order come first, in that order. Unknown ones follow,
// keeping their current left-to-right position.
function sortMonitors(monitors, order) {
  var list = (monitors || []).filter(isPackable).slice()
  var shared = sharedDescriptions(list)
  order = order || []
  list.sort(function(a, b) {
    var ra = rank(order, a, shared)
    var rb = rank(order, b, shared)
    if (ra !== -1 && rb !== -1) return ra - rb
    if (ra !== -1 || rb !== -1) return ra !== -1 ? -1 : 1
    var dx = (Number(a.x) || 0) - (Number(b.x) || 0)
    if (dx !== 0) return dx
    return String(a.name) < String(b.name) ? -1 : 1
  })
  return list
}

// Stack entries that can be used with `monitors` connected: the monitor and
// the one it stands on are both arrangeable, and following `on` never loops.
// { key: { on, side } } keyed like the row (monitorKey).
function activeStack(monitors, stack) {
  var list = (monitors || []).filter(isPackable)
  var shared = sharedDescriptions(list)
  var present = {}
  list.forEach(function(monitor) { present[monitorKey(monitor, shared)] = true })
  var active = {}
  for (var key in (stack || {})) {
    if (!Object.prototype.hasOwnProperty.call(stack, key) || !present[key]) continue
    var seen = {}
    var at = key
    var ok = true
    while (stack[at]) {
      if (seen[at] || !present[stack[at].on]) { ok = false; break }
      seen[at] = true
      at = stack[at].on
    }
    if (ok) active[key] = stack[key]
  }
  return active
}

// [{ name, x, y, changed }] for every arrangeable monitor. Row monitors go
// left to right, top-aligned; stacked ones are centered above or below the
// monitor they stand on. Everything is shifted so the layout starts at 0x0.
function computePositions(monitors, order, stack, monitorSettings) {
  var active = activeStack(monitors, stack)
  var list = (monitors || []).filter(isPackable)
  var shared = sharedDescriptions(list)
  var byKey = {}
  list.forEach(function(monitor) {
    byKey[monitorKey(monitor, shared)] = withSavedGeometry(monitor, shared, monitorSettings)
  })

  var placed = {}
  var row = sortMonitors(monitors, order).filter(function(monitor) {
    return !active[monitorKey(monitor, shared)]
  })
  var x = 0
  row.forEach(function(monitor) {
    var geom = withSavedGeometry(monitor, shared, monitorSettings)
    var size = logicalSize(geom)
    placed[monitorKey(monitor, shared)] = { monitor: geom, x: x, y: 0, w: size.w, h: size.h }
    x += size.w
  })

  function place(key) {
    if (placed[key]) return placed[key]
    var entry = active[key]
    var base = place(entry.on)
    var monitor = byKey[key]
    var size = logicalSize(monitor)
    placed[key] = {
      monitor: monitor,
      x: base.x + Math.round((base.w - size.w) / 2),
      y: entry.side === "above" ? base.y - size.h : base.y + base.h,
      w: size.w,
      h: size.h
    }
    return placed[key]
  }
  for (var key in active) place(key)

  var minX = 0
  var minY = 0
  for (var k in placed) {
    minX = Math.min(minX, placed[k].x)
    minY = Math.min(minY, placed[k].y)
  }

  // Row first, then stacked ones, each group in placement order.
  var result = []
  var keys = Object.keys(placed).sort(function(a, b) {
    var sa = active[a] ? 1 : 0
    var sb = active[b] ? 1 : 0
    if (sa !== sb) return sa - sb
    return placed[a].x - placed[b].x || placed[a].y - placed[b].y
  })
  keys.forEach(function(key) {
    var p = placed[key]
    var px = p.x - minX
    var py = p.y - minY
    result.push({
      name: String(p.monitor.name),
      x: px,
      y: py,
      changed: (Number(p.monitor.x) || 0) !== px || (Number(p.monitor.y) || 0) !== py
    })
  })
  return result
}

// Layout with `key` standing above or below `on`. Stacking on a side that
// already holds a monitor stacks onto that one instead, so they pile up.
// Returns the layout unchanged when it would stand on itself, directly or
// through others.
function withStacked(layout, key, on, side) {
  var stack = {}
  var source = (layout && layout.stack) || {}
  for (var k in source) {
    if (Object.prototype.hasOwnProperty.call(source, k) && k !== key) stack[k] = source[k]
  }
  var target = on
  var guard = 0
  var moved = true
  while (moved && guard++ < 64) {
    moved = false
    for (var other in stack) {
      if (stack[other].on === target && stack[other].side === side) {
        target = other
        moved = true
        break
      }
    }
  }
  for (var at = target, steps = 0; at && steps < 64; at = stack[at] && stack[at].on, steps++) {
    if (at === key) return copyLayout(layout)
  }
  stack[key] = { on: target, side: side === "below" ? "below" : "above" }
  var copy = copyLayout(layout)
  copy.stack = stack
  return copy
}

// Layout with `key` back in the row, at `index` among the row `rowKeys`
// (left to right, without `key`). Monitors that stood on it stay with it.
function withRowPosition(layout, key, rowKeys, index) {
  var keys = (rowKeys || []).filter(function(k) { return k !== key })
  keys.splice(Math.max(0, Math.min(keys.length, index)), 0, key)
  var copy = withOrder(layout, keys)
  var stack = {}
  var source = (layout && layout.stack) || {}
  for (var k in source) {
    if (Object.prototype.hasOwnProperty.call(source, k) && k !== key) stack[k] = source[k]
  }
  copy.stack = stack
  return copy
}

function copyLayout(layout) {
  return {
    order: ((layout && layout.order) || []).slice(),
    monitors: (layout && layout.monitors) || {},
    withExternal: cleanExternalMode(layout && layout.withExternal),
    stack: (layout && layout.stack) || {}
  }
}

// Only well-formed { on, side } entries keyed by a non-empty string.
function cleanStack(raw) {
  var stack = {}
  if (!raw || typeof raw !== "object") return stack
  for (var key in raw) {
    if (!Object.prototype.hasOwnProperty.call(raw, key) || key === "") continue
    var entry = raw[key]
    if (!entry || typeof entry.on !== "string" || entry.on === "" || entry.on === key) continue
    if (entry.side !== "above" && entry.side !== "below") continue
    stack[key] = { on: entry.on, side: entry.side }
  }
  return stack
}

// Where a tile dragged in the preview lands. `tiles`: [{ key, left, top,
// width, height, stacked }] at rest in preview coordinates; `from`: index of
// the dragged tile; (dx, dy): drag distance. The dragged tile's center over
// the top or bottom `edge` share of another tile (or clear above or below it,
// within its width) stacks it there: { side: "above" | "below", on: key },
// provided it was moved that way by at least a quarter of its own height, so
// a sideways drag never stacks by accident. A drag that leaves the packed
// group's left/right, or that is more sideways than vertical over a wifi
// column, joins the row at `index` among the other row tiles, left to right,
// by its center.
function dropTarget(tiles, from, dx, dy, edge) {
  var t = tiles && tiles[from]
  if (!t) return null
  var share = edge > 0 && edge < 0.5 ? edge : 0.3
  var cx = t.left + t.width / 2 + (dx || 0)
  var cy = t.top + t.height / 2 + (dy || 0)
  var adx = Math.abs(dx || 0)
  var ady = Math.abs(dy || 0)
  var vertical = ady >= t.height / 4
  var mainlyVertical = vertical && ady >= adx

  var rowLeft = Infinity
  var rowRight = -Infinity
  var overInternal = false
  for (var b = 0; b < tiles.length; b++) {
    rowLeft = Math.min(rowLeft, tiles[b].left)
    rowRight = Math.max(rowRight, tiles[b].left + tiles[b].width)
    if (b === from) continue
    if (tiles[b].internal && cx >= tiles[b].left && cx <= tiles[b].left + tiles[b].width)
      overInternal = true
  }
  var pastRow = rowRight > rowLeft && (cx < rowLeft || cx > rowRight)

  // Wifi tile: above/below is always the laptop, not USB-C sitting in that slot.
  // Past the left/right of the packed group, or a mainly-sideways drag, is a
  // row insert so the above-edge marker does not steal left/right placement.
  if (t.virtual && mainlyVertical && !pastRow) {
    var home = null
    for (var h = 0; h < tiles.length; h++) {
      if (h !== from && tiles[h].internal) { home = tiles[h]; break }
    }
    if (home) return { side: (dy || 0) < 0 ? "above" : "below", on: home.key }
  }
  var best = null
  for (var i = 0; i < tiles.length && vertical && !pastRow; i++) {
    if (i === from) continue
    var o = tiles[i]
    if (o.virtual) continue
    if (cx < o.left || cx > o.left + o.width) continue
    var bottom = o.top + o.height
    var side = null
    var distance = 0
    if (dy < 0 && cy < o.top + o.height * share) {
      side = "above"
      distance = Math.abs(cy - o.top)
    } else if (dy > 0 && cy > bottom - o.height * share) {
      side = "below"
      distance = Math.abs(cy - bottom)
    }
    if (side && (!best || distance < best.distance)) best = { distance: distance, on: o.key, side: side }
  }
  if (best) return { side: best.side, on: best.on }
  // Miracast sits in the packed row. A mainly-vertical drag over that column
  // (or over empty space above the row, still inside the group's x-span)
  // should still stack on the laptop. Past the left/right ends, or a drag
  // that is more sideways than vertical, stays a row insert.
  if (mainlyVertical && !pastRow && !overInternal) {
    var home = null
    for (var h = 0; h < tiles.length; h++) {
      if (h !== from && tiles[h].internal) { home = tiles[h]; break }
    }
    if (!home) {
      for (var p = 0; p < tiles.length; p++) {
        if (p !== from && !tiles[p].virtual) { home = tiles[p]; break }
      }
    }
    if (home) return { side: (dy || 0) < 0 ? "above" : "below", on: home.key }
  }

  var index = 0
  for (var j = 0; j < tiles.length; j++) {
    if (j === from || tiles[j].stacked) continue
    if (tiles[j].left + tiles[j].width / 2 < cx) index++
  }
  return { side: "row", index: index }
}

function luaString(value) {
  return "\"" + String(value).replace(/\\/g, "\\\\").replace(/"/g, "\\\"").replace(/\n/g, "\\n") + "\""
}

// First free x to the right of every monitor, both where they are now and
// where they are going. Staging monitors there keeps the move overlap-free.
function stagingX(monitors, positions, monitorSettings) {
  var right = 0
  var list = (monitors || []).filter(isPackable)
  var shared = sharedDescriptions(list.filter(isArrangeable))
  for (var i = 0; i < list.length; i++) {
    var geom = isVirtualHead(list[i]) ? list[i] : withSavedGeometry(list[i], shared, monitorSettings)
    right = Math.max(right, (Number(list[i].x) || 0) + logicalSize(geom).w)
  }
  for (var p = 0; p < (positions || []).length; p++) {
    var w = Number(positions[p].w)
    if (!(w > 0)) {
      var mon = null
      for (var m = 0; m < list.length; m++) {
        if (String(list[m].name) === String(positions[p].name)) { mon = list[m]; break }
      }
      w = mon ? logicalSize(isVirtualHead(mon) ? mon : withSavedGeometry(mon, shared, monitorSettings)).w : 0
    }
    right = Math.max(right, (Number(positions[p].x) || 0) + w)
  }
  var total = 0
  for (var j = 0; j < list.length; j++)
    total += logicalSize(isVirtualHead(list[j]) ? list[j] : withSavedGeometry(list[j], shared, monitorSettings)).w
  return Math.max(right, total)
}

function positionRule(name, x, y) {
  return "hl.monitor({ output = " + luaString(name) + ", position = \"" + x + "x" + y + "\" })"
}

// Position-only rules: Hyprland merges them into each monitor's existing rule,
// so mode, scale and the rest of the user's config stay untouched.
//
// Hyprland re-arranges after every rule, so moving monitors one by one straight
// to their targets can briefly stack two of them (swapping A|B: A moves onto
// B's spot while B is still there), which triggers Hyprland's "monitor layout
// overlaps" warning. With `staging`, every monitor first moves past the right
// edge of both layouts, then into place, so no intermediate state overlaps.
//
// `parked` lists outputs that were positioned before but are unplugged now.
// Hyprland keeps their last rule, so a monitor plugged back in would land on
// its old spot, which the compacted layout may now occupy, and trigger the same
// warning before the service can move it. Parking them at "auto-right" makes a
// returning monitor appear beside the layout instead.
function positionsToLua(positions, staging, parked) {
  var lines = []
  var phys = (positions || []).filter(function(p) { return !isVirtualHead({ name: p.name }) })
  var virt = (positions || []).filter(function(p) { return isVirtualHead({ name: p.name }) })
  if (staging !== undefined && staging !== null) {
    for (var i = 0; i < phys.length; i++)
      lines.push(positionRule(phys[i].name, staging + phys[i].x, phys[i].y))
  }
  for (var j = 0; j < phys.length; j++)
    lines.push(positionRule(phys[j].name, phys[j].x, phys[j].y))
  for (var k = 0; k < (parked || []).length; k++)
    lines.push("hl.monitor({ output = " + luaString(parked[k]) + ", position = \"auto-right\" })")
  // After every physical rule. A rejected HEADLESS rule aborts the rest of
  // the eval; placed earlier, that abort left eDP stacked at 0x0 (lock-screen
  // overlap, cursor on both). place-virtual-head repeats the move on its own
  // when this rule does not apply.
  for (var v = 0; v < virt.length; v++) {
    if (virt[v].changed)
      lines.push(positionRule(virt[v].name, virt[v].x, virt[v].y))
  }
  return lines.join("\n")
}

// True when two packable outputs share compositor space (cursor on both,
// Hyprland "monitor layout overlaps"). Lock reload of monitors.lua (eDP 0x0)
// while persistent-miracast is also at 0x0 is the usual case.
function rectsOverlap(ax, ay, aw, ah, bx, by, bw, bh) {
  return ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + ah
}

function packableOverlap(monitors) {
  var list = (monitors || []).filter(isPackable)
  for (var i = 0; i < list.length; i++) {
    var a = list[i]
    var asz = logicalSize(a)
    for (var j = i + 1; j < list.length; j++) {
      var b = list[j]
      var bsz = logicalSize(b)
      if (rectsOverlap(Number(a.x) || 0, Number(a.y) || 0, asz.w, asz.h, Number(b.x) || 0, Number(b.y) || 0, bsz.w, bsz.h))
        return true
    }
  }
  return false
}

// True when `box` shares area with a packable output other than `ignoreName`.
// Touching edges do not count. Used so place-virtual-head will not land the
// Extend head on eDP (Hyprland's overlap warning, cursor on both outputs).
function boxHitsPackable(monitors, box, ignoreName) {
  var x = Number(box && box.x) || 0
  var y = Number(box && box.y) || 0
  var w = Number(box && box.w) || 0
  var h = Number(box && box.h) || 0
  if (w <= 0 || h <= 0) return false
  var list = (monitors || []).filter(isPackable)
  for (var i = 0; i < list.length; i++) {
    if (ignoreName && String(list[i].name) === String(ignoreName)) continue
    var b = list[i]
    var bsz = logicalSize(b)
    if (rectsOverlap(x, y, w, h, Number(b.x) || 0, Number(b.y) || 0, bsz.w, bsz.h))
      return true
  }
  return false
}

// Position-only rules that move physical monitors to the packed row.
// The virtual head is omitted: miracast-ctl places it after this eval.
// When the head is not connected yet, `virtualHead` is inserted as a
// placeholder so eDP slides off the origin the new headless output occupies.
// Empty when every physical monitor is already there.
function landingLuaForConnect(monitors, layout, virtualHead) {
  var list = (monitors || []).slice()
  var spec = virtualHead || {}
  var vname = String(spec.name || "persistent-miracast")
  var have = false
  for (var i = 0; i < list.length; i++) {
    if (String(list[i].name) === vname) { have = true; break }
  }
  if (!have) {
    list.push({
      name: vname,
      description: vname,
      width: Number(spec.width) > 0 ? Number(spec.width) : 1920,
      height: Number(spec.height) > 0 ? Number(spec.height) : 1080,
      scale: Number(spec.scale) > 0 ? Number(spec.scale) : 1,
      transform: 0,
      x: -12000,
      y: 0,
      disabled: false,
      dpmsStatus: true,
      focused: false,
      mirrorOf: "none",
      miracast: true
    })
  }
  var positions = computePositions(
    list,
    (layout && layout.order) || [],
    (layout && layout.stack) || {},
    (layout && layout.monitors) || {}
  )
  var lines = []
  for (var p = 0; p < positions.length; p++) {
    if (isVirtualHead({ name: positions[p].name })) continue
    if (!positions[p].changed) continue
    lines.push(positionRule(positions[p].name, positions[p].x, positions[p].y))
  }
  return lines.join("\n")
}

function logicalBox(monitor) {
  var size = logicalSize(monitor)
  return {
    x: Number(monitor && monitor.x) || 0,
    y: Number(monitor && monitor.y) || 0,
    w: size.w,
    h: size.h
  }
}

function pointInBox(box, x, y) {
  return x >= box.x && y >= box.y && x < box.x + box.w && y < box.y + box.h
}

// null when the pointer is already on a physical monitor: do not teleport it.
// Otherwise land it on `primaryName` at the same relative spot it had on the
// virtual head, or at the nearest point of the laptop if it is in empty space.
// Never the center. A reconnect that always warps to center is the jump.
function cursorRescue(monitors, cursor, primaryName) {
  var x = Number(cursor && cursor.x) || 0
  var y = Number(cursor && cursor.y) || 0
  var list = monitors || []
  var primary = null
  var onPhysical = false
  var virtualHit = null
  for (var i = 0; i < list.length; i++) {
    var box = logicalBox(list[i])
    if (box.w <= 0 || box.h <= 0) continue
    if (String(list[i].name) === String(primaryName)) primary = box
    if (!pointInBox(box, x, y)) continue
    if (isVirtualHead(list[i])) {
      if (!virtualHit) virtualHit = box
    } else {
      onPhysical = true
    }
  }
  if (onPhysical || !primary) return null
  var dx = x - (virtualHit ? virtualHit.x : primary.x)
  var dy = y - (virtualHit ? virtualHit.y : primary.y)
  if (virtualHit && virtualHit.w > 0) dx = dx * primary.w / virtualHit.w
  if (virtualHit && virtualHit.h > 0) dy = dy * primary.h / virtualHit.h
  dx = Math.max(0, Math.min(primary.w - 1, Math.round(dx)))
  dy = Math.max(0, Math.min(primary.h - 1, Math.round(dy)))
  var nx = primary.x + dx
  var ny = primary.y + dy
  if (nx === x && ny === y) return null
  return { x: nx, y: ny }
}

// After a monitor moves, keep a pointer that was on a physical output on that
// same pixel. Virtual heads are ignored so parking one cannot drag the cursor
// to -12000.
function cursorFollow(before, after, cursor) {
  var x = Number(cursor && cursor.x) || 0
  var y = Number(cursor && cursor.y) || 0
  var host = null
  var list = before || []
  for (var i = 0; i < list.length; i++) {
    if (isVirtualHead(list[i])) continue
    var box = logicalBox(list[i])
    if (box.w <= 0 || box.h <= 0) continue
    if (pointInBox(box, x, y)) { host = list[i]; break }
  }
  if (!host) return null
  var now = null
  var next = after || []
  for (var j = 0; j < next.length; j++) {
    if (String(next[j].name) === String(host.name)) { now = next[j]; break }
  }
  if (!now) return null
  var oldBox = logicalBox(host)
  var newBox = logicalBox(now)
  var nx = newBox.x + (x - oldBox.x)
  var ny = newBox.y + (y - oldBox.y)
  if (nx === x && ny === y) return null
  return { x: nx, y: ny }
}

function parkedOutputs(known, positions) {
  var placed = {}
  for (var i = 0; i < positions.length; i++) placed[positions[i].name] = true
  return (known || []).filter(function(name) { return !placed[name] })
}

function moveItem(list, from, to) {
  var copy = list.slice()
  if (from < 0 || from >= copy.length || to < 0 || to >= copy.length || from === to) return copy
  var moved = copy.splice(from, 1)[0]
  copy.splice(to, 0, moved)
  return copy
}

// Where a dragged tile lands: after every other tile whose center its leading
// edge has crossed. Comparing centers instead fails for mismatched sizes, since
// a wide tile's center cannot get past a narrow neighbour's inside the preview.
// tiles: [{ left, width }] at rest; offset: horizontal drag distance.
function dropIndex(tiles, from, offset) {
  if (!tiles || from < 0 || from >= tiles.length || !offset) return from
  var left = tiles[from].left + offset
  var edge = offset < 0 ? left : left + tiles[from].width
  var to = 0
  for (var i = 0; i < tiles.length; i++) {
    if (i === from) continue
    if (tiles[i].left + tiles[i].width / 2 < edge) to++
  }
  return to
}

// View model for the panel: arrangeable monitors sorted by current position,
// left to right then top to bottom. `stacked` marks the ones standing on
// another monitor (see activeStack).
function tilesFromMonitors(monitors, stack, monitorSettings, order) {
  var layoutOrder = order || []
  var packed = computePositions(monitors, layoutOrder, stack, monitorSettings)
  var byName = {}
  for (var p = 0; p < packed.length; p++) byName[packed[p].name] = packed[p]
  var active = activeStack(monitors, stack)
  var previewable = (monitors || []).filter(isPreviewable)
  var shared = sharedDescriptions(previewable.filter(isPackable))
  var labelCount = {}
  previewable.forEach(function(monitor) {
    var label = tileLabel(monitor)
    labelCount[label] = (labelCount[label] || 0) + 1
  })
  var list = previewable.map(function(monitor) {
    var geom = isVirtualHead(monitor) ? monitor : withSavedGeometry(monitor, shared, monitorSettings)
    var size = logicalSize(geom)
    var label = tileLabel(monitor)
    var virtual = isVirtualHead(monitor)
    var key = virtual ? String(monitor.name) : monitorKey(monitor, shared)
    var slot = byName[String(monitor.name)]
    return {
      name: String(monitor.name),
      key: key,
      label: labelCount[label] > 1 ? label + " · " + monitor.name : label,
      internal: isInternal(monitor),
      virtual: virtual,
      focused: monitor.focused === true,
      stacked: !!active[key],
      x: slot ? slot.x : (Number(monitor.x) || 0),
      y: slot ? slot.y : (Number(monitor.y) || 0),
      w: size.w,
      h: size.h
    }
  })
  list.sort(function(a, b) { return a.x - b.x || a.y - b.y })
  return list
}

// Put the Miracast tile outside the packed physical row. Placing it only
// against eDP overlapped USB-C when that panel already sat left of the laptop.
// Packed x,y for the first virtual head (computePositions + stack).
function packedVirtualXY(monitors, layout) {
  var list = monitors || []
  var virt = null
  for (var i = 0; i < list.length; i++) {
    if (isVirtualHead(list[i])) { virt = list[i]; break }
  }
  if (!virt) return { x: 0, y: 0 }
  var order = ((layout && layout.order) || []).slice()
  var vname = String(virt.name)
  if (order.indexOf(vname) < 0) order.push(vname)
  var positions = computePositions(
    list, order, (layout && layout.stack) || {}, (layout && layout.monitors) || {}
  )
  for (var p = 0; p < positions.length; p++) {
    if (String(positions[p].name) === vname)
      return { x: positions[p].x, y: positions[p].y }
  }
  return { x: 0, y: 0 }
}

// Arrangement drop of the Miracast tile: row insert, or stack above/below a physical tile.
function applyVirtualDrop(layout, virtKey, target, rowKeys) {
  if (!layout || !virtKey) return layout
  if (!target) return layout
  if (target.side === "row")
    return withRowPosition(layout, virtKey, rowKeys || [], target.index)
  if ((target.side === "above" || target.side === "below") && target.on && target.on !== virtKey)
    return withVirtualStacked(layout, virtKey, target.on, target.side)
  return layout
}

// Miracast above/below a physical monitor. Do not pile on USB-C that already
// occupies that side — that is the DISPLAY SETTINGS "above Built-In" miss.
function withVirtualStacked(layout, virtKey, on, side) {
  if (!virtKey || !on || virtKey === on) return copyLayout(layout)
  var stack = {}
  var source = (layout && layout.stack) || {}
  var dir = side === "below" ? "below" : "above"
  for (var k in source) {
    if (!Object.prototype.hasOwnProperty.call(source, k) || k === virtKey) continue
    if (source[k].on === on && source[k].side === dir) continue
    stack[k] = source[k]
  }
  stack[virtKey] = { on: on, side: dir }
  var copy = copyLayout(layout)
  copy.stack = stack
  return copy
}

function _internalKey(monitors) {
  var list = monitors || []
  for (var i = 0; i < list.length; i++) {
    if (isInternal(list[i]) && isArrangeable(list[i])) return monitorKey(list[i])
  }
  for (var j = 0; j < list.length; j++) {
    if (isArrangeable(list[j])) return monitorKey(list[j])
  }
  return ""
}

function _virtKey(monitors) {
  var list = monitors || []
  for (var i = 0; i < list.length; i++) {
    if (isVirtualHead(list[i])) return String(list[i].name)
  }
  return ""
}

function _rowKeysWithout(layout, monitors, skip) {
  var order = (layout && layout.order) || []
  var stack = activeStack(monitors, (layout && layout.stack) || {})
  var keys = []
  var seen = {}
  function push(key) {
    if (!key || key === skip || seen[key] || stack[key]) return
    seen[key] = true
    keys.push(key)
  }
  for (var i = 0; i < order.length; i++) push(order[i])
  var list = monitors || []
  var shared = sharedDescriptions(list.filter(isPackable))
  for (var j = 0; j < list.length; j++) {
    if (isVirtualHead(list[j])) push(String(list[j].name))
    else if (isArrangeable(list[j])) push(monitorKey(list[j], shared))
  }
  return keys
}

// Pills Left/Right/Above/Below → layout.order + layout.stack.
function layoutWithExtendPosition(layout, monitors, position) {
  var virtKey = _virtKey(monitors)
  var edpKey = _internalKey(monitors)
  if (!virtKey) return copyLayout(layout)
  var pos = String(position || "right")
  if (pos === "above" || pos === "below") {
    if (!edpKey) return copyLayout(layout)
    return withVirtualStacked(layout, virtKey, edpKey, pos)
  }
  var row = _rowKeysWithout(layout, monitors, virtKey)
  if (pos === "left") return withRowPosition(layout, virtKey, row, 0)
  return withRowPosition(layout, virtKey, row, row.length)
}

function applyExtendPreview(tiles, extendPosition) {
  var virt = null
  var left = Infinity
  var right = -Infinity
  var top = Infinity
  var bottom = -Infinity
  var rowY = 0
  for (var i = 0; i < (tiles || []).length; i++) {
    if (tiles[i].virtual) { virt = tiles[i]; continue }
    left = Math.min(left, tiles[i].x)
    right = Math.max(right, tiles[i].x + tiles[i].w)
    top = Math.min(top, tiles[i].y)
    bottom = Math.max(bottom, tiles[i].y + tiles[i].h)
    if (tiles[i].internal) rowY = tiles[i].y
  }
  if (!virt || left === Infinity) return tiles
  var pos = String(extendPosition || "right")
  if (pos === "left") {
    virt.x = left - virt.w
    virt.y = rowY
  } else if (pos === "above") {
    virt.x = left + Math.round((right - left - virt.w) / 2)
    virt.y = top - virt.h
  } else if (pos === "below") {
    virt.x = left + Math.round((right - left - virt.w) / 2)
    virt.y = bottom
  } else {
    virt.x = right
    virt.y = rowY
  }
  return tiles
}

// Map an Arrangement drop of the Miracast tile to extendPosition.
function extendPositionFromDrop(tiles, from, target, dx) {
  if (!tiles || from < 0 || from >= tiles.length) return ""
  var virt = tiles[from]
  if (!virt || !virt.virtual) return ""
  var edp = null
  for (var i = 0; i < tiles.length; i++) {
    if (tiles[i].internal) { edp = tiles[i]; break }
  }
  if (!edp) return "right"
  if (target && (target.side === "above" || target.side === "below") && target.on === edp.key)
    return target.side
  var cx = virt.x + (Number(dx) || 0) + virt.w / 2
  var left = Infinity
  var right = -Infinity
  for (var j = 0; j < tiles.length; j++) {
    if (tiles[j].virtual) continue
    left = Math.min(left, tiles[j].x)
    right = Math.max(right, tiles[j].x + tiles[j].w)
  }
  if (left === Infinity) {
    var ecx = edp.x + edp.w / 2
    return cx < ecx ? "left" : "right"
  }
  return cx < (left + right) / 2 ? "left" : "right"
}

// The Display panel's DISPLAYS rows with one output switched on or off, before
// omarchy-monitor-state reports it: { displays, enabledDisplayCount }, as
// Model.parseDisplays returns. The list and the changed row are copies.
function withDisplayEnabled(displays, name, enabled) {
  var list = []
  var count = 0
  for (var i = 0; i < (displays || []).length; i++) {
    var display = displays[i]
    if (display && display.name === name) {
      var copy = {}
      for (var field in display) copy[field] = display[field]
      copy.enabled = enabled
      display = copy
    }
    if (display && display.enabled) count++
    list.push(display)
  }
  return { displays: list, enabledDisplayCount: count }
}

if (typeof module !== "undefined") {
  module.exports = {
    monitorKey: monitorKey,
    sharedDescriptions: sharedDescriptions,
    isInternal: isInternal,
    isVirtualHead: isVirtualHead,
    isParkedVirtual: isParkedVirtual,
    isPreviewable: isPreviewable,
    isPresenting: isPresenting,
    isArrangeable: isArrangeable,
    logicalSize: logicalSize,
    withSavedGeometry: withSavedGeometry,
    tileLabel: tileLabel,
    cleanSettings: cleanSettings,
    parseLayout: parseLayout,
    parseOrder: parseOrder,
    serializeLayout: serializeLayout,
    serializeOrder: serializeOrder,
    withMonitorSettings: withMonitorSettings,
    parseMode: parseMode,
    formatRefresh: formatRefresh,
    modeString: modeString,
    resolutionOptions: resolutionOptions,
    refreshOptions: refreshOptions,
    liveSettings: liveSettings,
    settingsMatch: settingsMatch,
    rejectedFields: rejectedFields,
    cleanExternalMode: cleanExternalMode,
    withOrder: withOrder,
    withExternalMode: withExternalMode,
    shouldHoldLayout: shouldHoldLayout,
    externalModeCommand: externalModeCommand,
    extendCommands: extendCommands,
    settingsRule: settingsRule,
    pendingSettings: pendingSettings,
    settingsToLua: settingsToLua,
    snapshotPhysicalSettings: snapshotPhysicalSettings,
    physicalReloadLua: physicalReloadLua,
    diagonalInches: diagonalInches,
    pixelDensity: pixelDensity,
    rotationLabel: rotationLabel,
    mergeOrder: mergeOrder,
    sortMonitors: sortMonitors,
    computePositions: computePositions,
    activeStack: activeStack,
    withStacked: withStacked,
    withRowPosition: withRowPosition,
    cleanStack: cleanStack,
    dropTarget: dropTarget,
    stagingX: stagingX,
    positionsToLua: positionsToLua,
    packableOverlap: packableOverlap,
    boxHitsPackable: boxHitsPackable,
    landingLuaForConnect: landingLuaForConnect,
    cursorRescue: cursorRescue,
    cursorFollow: cursorFollow,
    parkedOutputs: parkedOutputs,
    moveItem: moveItem,
    dropIndex: dropIndex,
    isPackable: isPackable,
    migrateLayoutOrder: migrateLayoutOrder,
    tilesFromMonitors: tilesFromMonitors,
    packedVirtualXY: packedVirtualXY,
    applyVirtualDrop: applyVirtualDrop,
    withVirtualStacked: withVirtualStacked,
    layoutWithExtendPosition: layoutWithExtendPosition,
    applyExtendPreview: applyExtendPreview,
    extendPositionFromDrop: extendPositionFromDrop,
    withDisplayEnabled: withDisplayEnabled
  }
}
