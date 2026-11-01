-- Loaded from ~/.config/hypr/bindings.lua when realchrisolin.display is installed.
-- SUPER+SHIFT+ALT+arrows still moves the whole workspace (Omarchy tiling.lua).
-- These send only the focused window onto the other display's active workspace.
o.bind(
  "SUPER + SHIFT + CTRL + LEFT",
  "Move window to left monitor",
  hl.dsp.window.move({ monitor = "l" })
)
o.bind(
  "SUPER + SHIFT + CTRL + RIGHT",
  "Move window to right monitor",
  hl.dsp.window.move({ monitor = "r" })
)
