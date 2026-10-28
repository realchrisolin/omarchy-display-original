# Handoff: Hyprland ICC screenshare redraw fix

Last updated: 2026-09-13  
Status: **validated locally**; fork branch **pushed** (`a73e6bd8`); **upstream PR not opened**

## Goal

Upstream the Hyprland change so ICC screenshare clients keep receiving frames on
idle or headless outputs without waiting for unrelated activity (for example
pointer motion). Prefer ICC for GPU cost; stock wlr-screencopy remains a
fallback.

## Root cause

In `CScreenshareFrame::share()`, Hyprland only called `scheduleFrame` /
`damageMonitor` when `m_isFirst` was true.

wlr-screencopy damages the monitor on (nearly) every share. With ICC, a quiet
headless output could keep a stale framebuffer until an unrelated redraw.

Evidence from Miracast Extend validation:

- `grim` of the Extend head already showed fully typed text
- Stock `/usr/bin/wf-recorder` (wlr-screencopy) did not show the typing lag
- Always scheduling on share resolved the lag in session

Related notes: [icc-text-delay-debug.md](icc-text-delay-debug.md)

## Change

On every share (when a monitor exists), call:

- `PMONITOR->scheduleFrame(AQ_SCHEDULE_NEEDS_FRAME)`
- `g_pHyprRenderer->damageMonitor(PMONITOR)`

`m_isFirst` still controls full vs incremental buffer damage later in the same
function. The null monitor pointer is guarded before `damageMonitor`.

## Branch / packaging

| Item | Location |
|------|----------|
| Upstream | https://github.com/hyprwm/Hyprland |
| Fork | https://github.com/realchrisolin/Hyprland |
| Branch | `fix/icc-screenshare-schedule-every-share` |
| Commit | `a73e6bd8c4502dd4eab24b2e53c0b7724c4cc58b` |
| Local clone | `$HOME/src/Hyprland-icc-pr` |
| Compare | https://github.com/hyprwm/Hyprland/compare/main...realchrisolin:Hyprland:fix/icc-screenshare-schedule-every-share?expand=1 |

Patch copies in this repo:

- `hyprland-patches/icc-schedule-every-share.patch`
- `hyprland-patches/0001-fix-schedule-ICC-screenshare-present-on-every-share.patch`

Local install used for validation:

- Prefix: `~/.local/hyprland-icc-fix/`
- UWSM: `~/.config/uwsm/env.d/50-hyprland-icc-fix` (prepends that `bin/` so `start-hyprland` `execvp`s it)
- Toggle: `~/.local/hyprland-icc-fix/toggle-icc-fix.sh {on,off,status}`
- Running binary (2026-09-21): commit `8bd33cea` on `fix/icc-screenshare-schedule-every-share`, tag `v0.56.0-191-g8bd33cea`. Not Arch `hyprland 0.56.2-2`.

### Two different Hyprlands

The ICC patch is a few lines in `ScreenshareFrame.cpp`. It does **not** add Lua IPC.

| | Arch `/usr/bin/Hyprland` 0.56.2 | This prefix (`8bd33cea`, `v0.56.0-191`) |
|--|----------------------------------|------------------------------------------|
| Config / dispatch | Classic `hyprctl` | Lua: `hl.dsp.exec_cmd`, `hl.dsp.focus`, `hl.dsp.cursor.move` |
| Nested workspace JSON | `{"id": N, "name": "…"}` | `{"address","type","name"}` — **no `.id`** |
| What breaks | Omarchy `omarchy-capture-region` works | Smart screenshot `jq` dies (`"null" \| tonumber`); slurp exits immediately |

Hyprland `main` has since started emitting an optional numeric `"id"` again. Omarchy `quattro` `bin/omarchy-capture-region` still queries only `.id` ([omacom/omarchy#11903](https://github.com/omacom/omarchy/issues/11903), closed not-planned, same failure). Do not treat a screenshot failure on this prefix as an ICC-patch bug.

### omarchy-miracast packaging

- Plugin source + tracked `.so`: `hyprland-plugins/icc-present-kick/`
- `miracast-ctl` loads the plugin when `PROTO=icc`, unloads on stop
- Temporary fallback while Arch Hyprland lacks the upstream fix

## Upstream PR checklist

1. Read [PR Guidelines](https://wiki.hypr.land/Contributing-and-Debugging/PR-Guidelines/)
2. Be [vouched](https://wiki.hypr.land/Contributing-and-Debugging/#getting-vouched) (required)
3. Follow the [AI Usage Policy](https://github.com/hyprwm/.github/blob/main/policies/AI_USAGE.md)
4. Open PR: `hyprwm/Hyprland:main` ← `realchrisolin:fix/icc-screenshare-schedule-every-share`
5. Test plan: ICC capture on a headless/Extend output; type without moving the pointer

## Re-validate after merge / new Hyprland package

```bash
~/.local/hyprland-icc-fix/toggle-icc-fix.sh status
hyprctl version
# Miracast: wfRecorderBin → ICC build, wfRecorderProto → icc
```

## Optional cleanup after upstream merge

- [ ] Stop auto-loading `icc-present-kick` once Arch includes the fix
- [ ] Revisit `softwareCursors` defaults once ICC redraw is solid on stock Hyprland

## Do not

- Re-enable the old function-hook plugin variant (crashed Hyprland)
- Force full-session `forceFullFrames` every tick (caused artifacts)
