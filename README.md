# Omarchy Display + Miracast

Extends the Omarchy **Display** bar panel (brightness, text size, scale,
per-output controls) with **Miracast / Wi‑Fi Display** mirror and extend.

Branch **`v2-dev`** vendors [kris-1/omarchy-monitor-layout](https://github.com/kris-1/omarchy-monitor-layout)
(drag-and-drop arrangement) and hosts Miracast in `MiracastSection.qml`. See
[`docs/V2.md`](docs/V2.md). `master` still uses `DisplayPanel.qml` without that layout UI.

This is still the Display dropdown — not a separate cast icon.

Cloned from first-party `omarchy.monitor`, then extended.

**Local performance PoC** (custom ICC `wf-recorder`, screencopy vs ICC,
why upstream merges matter): see **[BUILD.md](BUILD.md)**.  
**Measured CPU / encode matrix** (charts): see **[BENCHMARKS.md](BENCHMARKS.md)**.

## Features

- Scan / connect / disconnect Miracast sinks from the Display panel
- **Mirror** or **Extend** (Hyprland virtual output named after the sink)
- Stream mode pills (sink-advertised CEA modes such as 720p30 / 1080p30)
- P2P Wi‑Fi radio picker (Auto prefers idle P2P-GO adapters; optional quiet-channel CSA)
- Safe scale / position changes (pause capture → move → restart)
- Safer disconnect teardown (workspace migrate, cursor restore, eDP re-assert)
- Optional VAAPI/QSV encode with OS power-plan throttling (FluxCast `power_plan_N`)
- **Persist display across monitors** (default on): switching Miracast sinks keeps the same Extend desktop on a shared Hyprland output named `persistent-miracast`; off uses a peer-named head and seeds a fresh desktop. Empty leftover heads from earlier peer names are **not** destroyed (Hyprland `output remove` can freeze eDP); `miracast-ctl status` lists them as `orphanExtendHeads`. They clear on Hyprland restart.
- **Start** disconnects a Wi-Fi STA already on **192.168.49.0/24** (WFD P2P subnet — phone hotspots often use it). Ethernet / docker / VPN on that range are logged and left up. **Stop** reaps leftover `fluxcast-dnsmasq` on old `p2p-wlp0s20-*` groups.

## Install

You need three pieces: this **Display** plugin, OS packages, and a **FluxCast**
tree with the WFD patches this panel expects. The bar label stays **Display**.

### 1. Packages

```bash
omarchy pkg add dnsmasq wf-recorder xorg-xrandr ffmpeg
```

Also needed (usually already present on Omarchy): NetworkManager, PipeWire /
WirePlumber or PulseAudio, `iw`, `nmcli`, Python 3. Optional: `ufw` so
**Doctor** can open Miracast ports for you.

### 2. Install the plugin

**From git (recommended for users):**

```bash
omarchy plugin add https://github.com/realchrisolin/omarchy-miracast.git --enable
```

That clones into `~/.config/omarchy/plugins/<id>/` (id comes from
`manifest.json`, e.g. `realchrisolin.monitor`), places the bar widget, and enables it.
Disable the stock Display widget if it is still enabled:

```bash
omarchy plugin disable omarchy.monitor
omarchy plugin list   # expect your *.monitor enabled, omarchy.monitor disabled
```

**From a local checkout (developers):** keep one git tree and symlink it so edits
hot-reload without copying:

```bash
git clone https://github.com/realchrisolin/omarchy-miracast.git ~/code/other/omarchy-miracast
mkdir -p ~/.config/omarchy/plugins
ln -sfn ~/code/other/omarchy-miracast ~/.config/omarchy/plugins/realchrisolin.monitor

omarchy plugin validate ~/.config/omarchy/plugins/realchrisolin.monitor
omarchy plugin enable realchrisolin.monitor --section right   # or left / center
omarchy plugin disable omarchy.monitor
```

Confirm `~/.config/omarchy/shell.json` bar layout references your plugin id
(e.g. `"id": "realchrisolin.monitor"`), not `omarchy.monitor`. Soft-reload:

```bash
omarchy-shell shell rescanPlugins
```

QML icon/layout changes sometimes need a full shell restart:

```bash
rm -rf ~/.cache/quickshell/qmlcache
omarchy restart shell
```

### 3. FluxCast

Point Miracast at a FluxCast **source tree** (not an AppImage alone). Prefer a
fork that already includes the Omarchy WFD work (encode.env reload, LPCM,
pipe/DMA-BUF, SIGUSR1 restart), e.g.
[realchrisolin/fluxcast](https://github.com/realchrisolin/fluxcast)
`feat/wfd-hw-encode-modes`, or apply `patches/fluxcast/` onto upstream
[IlyaP358/fluxcast](https://github.com/IlyaP358/fluxcast) — see
[`patches/fluxcast/APPLY.md`](patches/fluxcast/APPLY.md).

```bash
git clone https://github.com/realchrisolin/fluxcast.git ~/code/other/fluxcast
cd ~/code/other/fluxcast && git checkout feat/wfd-hw-encode-modes   # if using that fork
```

`miracast-ctl` resolves FluxCast in this order:

1. `$FLUXCAST_ROOT` (environment)
2. `fluxcastRoot` in `~/.config/omarchy-miracast/settings.json` (`~/…` or `$HOME/…` OK)
3. Sibling `../fluxcast` next to this plugin checkout (e.g. `~/code/other/fluxcast` beside `~/code/other/omarchy-miracast`)

```bash
# Portable — prefer $HOME, not a hard-coded /home/<user>/…
export FLUXCAST_ROOT="${FLUXCAST_ROOT:-$HOME/code/other/fluxcast}"
# Or persist:
#   { "fluxcastRoot": "$HOME/code/other/fluxcast" }  in settings.json
```

If an old AppImage extract still lives under
`vendor/squashfs-root/usr/src/fluxcast`, replace that directory with a
**symlink** to the git checkout so paths cannot drift.

### 4. Optional: `miracast-ctl` on PATH

The panel always runs `pluginDir/bin/miracast-ctl`. For a terminal:

```bash
mkdir -p ~/.local/bin
ln -sfn ~/.config/omarchy/plugins/realchrisolin.monitor/bin/miracast-ctl ~/.local/bin/miracast-ctl
# ~/.local/bin is usually already on PATH on Omarchy
miracast-ctl status
miracast-ctl doctor
```

### 5. Smoke-check

```bash
miracast-ctl doctor          # or: Doctor in the Display panel
miracast-ctl scan            # nearby Miracast sinks
```

Put the TV/dongle in Miracast / screen-mirroring receive mode, then **Scan** and
connect from the Display panel. Day-to-day tips (audio, channels, 2.4-only
dongles): panel **Info**, or [`docs/MIRACAST-HELP.md`](docs/MIRACAST-HELP.md).

**Hardware note:** some Miracast sticks **listen** on 2.4 GHz but still accept a
**5 GHz operating channel** (hotyeah / Realtek 8192CU often: `listen_freq=2437`,
`oper_freq=5220`). Status uses `p2pFreqSource=peer_oper` in that case — do not
treat listen as air. True **2.4-only** sinks (oper stays on 2.4 while STA is
5 GHz) force MCC; Doctor warns as `radio_mcc`. On true 5 GHz SCC with HT20 P2P
next to a wider STA, Doctor may warn `radio_scc_tax` (one-radio airtime); set
`p2pWifiInterface` to a second idle NIC when available.

## Settings

`status` JSON includes live radio fields (no SSIDs): `staChannel`, `p2pChannel`,
`staWidthMHz`, `p2pRole`, `radioMcc`, `p2pFreqSource` (`peer_oper` /
`peer_listen`), `p2pListenFreqMHz` / `p2pOperFreqMHz`.

Override in `~/.config/omarchy-miracast/settings.json` (merged with
`miracast-ctl` defaults on read):

| Key | Default | Notes |
|-----|---------|--------|
| `mode` | `mirror` | `mirror` or `extend` |
| `extendPosition` | `right` | `left` / `right` / `above` / `below` |
| `streamMode` | `1280x720p30` | e.g. `1920x1080p30` — drives fps + resolution |
| `fps` | `20` | Fallback when `streamMode` is unset |
| `outputRes` | `1280x720` | Encoded size (fallback) |
| `extendResolution` | `1280x720` | Extend virtual output size (fallback) |
| `extendRefresh` | stream fps (clamped to advertised HEADLESS modes, typically **60**) | Virtual output Hz. Hyprland HEADLESS often lists only 60 Hz — do not invent 30 Hz (ICC stalls, ffmpeg IO watchdog rebinds). `scripts/headless_refresh.py` picks the live RTSP fps when advertised. |
| `bitrate` | `8M` | Current encode target. Under `encodeStrategy=smartview` ABR uses Samsung dig **2–14 Mbps** (init **8M**). Interactive kenya/hotyeah profile uses **CBR** (AOSP `OMX_Video_ControlRateConstant`); QVBR on Intel undershoots (~0.2 Mbps) and turns a 0.25 s VBV into seconds of lag. |
| `videoEncoder` | `auto` | `auto` → VAAPI, else NVENC, else QSV, else `libx264` |
| *(env)* `FLUXCAST_WFD_CAPTURE_ENCODE` | `auto` (Omarchy) / `pipe` (upstream) | `auto`/`vaapi` = wf-recorder DMA-BUF encode (incl. scaled outputs); `pipe` = raw→ffmpeg hwupload |
| *(env)* `FLUXCAST_WFD_DMABUF_ALLOW_SCALED` | allow (default) | `0`/`false` = force pipe when Hyprland scale ≠ 1 |
| `encodeStrategy` | `smartview` | `smartview` = DMA-BUF + BitrateController (Samsung 2/8/14M, qmin/qmax 15–44). **CBR** is the interactive RC (AOSP Converter.cpp); QVBR remains available if `vaapiRcMode` is set. `performance` = DMA-BUF CQP. |
| `captureEncode` | `dmabuf` | RENDER ENGINE: `dmabuf` (GPU + DMA-BUF) / `vaapi` (GPU pipe) / `cpu` |
| `audioEnabled` | `true` | PipeWire/Pulse **Miracast** null sink; FluxCast captures **`miracast.monitor`**. If the sink lists LPCM, FluxCast muxes WFD **`stream_type=0x83`** (hotyeah / many Realtek dongles are LPCM-only — AAC is silent). AAC only when LPCM is absent or `FLUXCAST_WFD_FORCE_AAC=1`. Do **not** use ffmpeg `aresample=async` (held ~0.5 s). Keep the Miracast sink near **100%**. See [BUILD.md §6](BUILD.md). |
| `autoSwitchAudioOutput` | `true` | Panel: **Automatically switch audio output**. On: default sink → Miracast at PLAY (speakers held during connect). Off: leave the currently selected output; still create the Miracast sink for manual routing / capture. |
| `softwareCursors` | `true` | Force SW cursors so the pointer appears on the TV (HW cursor plane is not captured). |
| `wfRecorderBin` | unset | Absolute path to a custom `wf-recorder`. **Required for QVBR target hit** (build with `rc_min_rate` apply). Empty = PATH stock (undershoots QVBR to ~3 Mbps). ICC/PR #347 optional for capture pacing; see [BUILD.md §7](BUILD.md). |
| `wfRecorderProto` | `auto` | `auto` / `icc` / `wlr`. `auto` upgrades to `icc` when a configured binary advertises ICC. Use `wlr` + stock binary if cast-head terminal keys feel buffered until the pointer moves. |
| `wfRecorderDamage` | `"1"` | `"1"` = damage-aware (omit `wf-recorder -D`); `"0"` = continuous `-D`. Set by `scripts/recommend-cast-profile.py --apply` or manually. |
| `captureEncode` | `dmabuf` | Render engine: `dmabuf` \| `vaapi` (GPU pipe) \| `cpu`. |
| `encodeProfile` | `medium` | Quality: **best\|veryhigh\|high\|medium\|low** — knobs **per engine** (`scripts/encode_quality_presets.py`). |
| `castPreset` | `desktop` | Content hint: `desktop` = damage-aware; `movie` = continuous `-D`. |
| `vaapiQuality` | *(from profile)* | ffmpeg `h264_vaapi` `-quality` (1–8; higher = faster/worse). |
| `vbvMultiplier` | `0.25` (CBR) / `0.1` cap (QVBR) | CBR: Intel low-delay HRD **0.25 s** of target (smaller pumped quality on iHD). QVBR: cap seconds; FluxCast sizes `bufsize` from ~4 frames so undershoot cannot turn `peak×0.25` into many seconds. → `FLUXCAST_WFD_VBV_MULTIPLIER`. |
| `p2pWifiInterface` | `auto` | Managed Wi‑Fi iface for Miracast P2P, or `auto` (prefer **idle** P2P-GO NIC so Miracast is not time-sliced with home STA). USB names change on re-plug; a missing saved iface is resolved to a live radio of the same role, not kept as a stale name. |
| `p2pGo5GHz` | `false` | USB GO only: keep 5 GHz in the GO channel set. Default drops 5 GHz (`p2p_no_go_freq`). After PLAY, FluxCast may 802.11-CSA to 2.4 if the phy cannot carry 5 GHz WFD; a sink that does not follow is remembered (`p2p-csa-nofollow`) and the hop is skipped next time. Ignored on NetworkManager ifaces. |
| `usbWpaSupplicant` | *(empty)* | Absolute path to `wpa_supplicant` for dedicated USB P2P. Empty = `PATH`. Also `FLUXCAST_USB_WPA`. |
| `p2pQuietCsa` | `false` | `true` = post-PLAY CSA to a quiet channel (MCC). Default **SCC**. |
| `vaapiRcMode` | *(from profile)* | `CQP` / `QVBR` / `CBR` / `VBR` → `FLUXCAST_WFD_VAAPI_RC`. |
| `vaapiBitrate` | *(from profile)* | QVBR/CBR peak (`FLUXCAST_WFD_VAAPI_BITRATE`). |
| `vaapiQp` | *(from profile)* | Quantizer (lower = sharper). |
| `vaapiGop` | `60` at 1080p60 | GOP frames (~1 s IDR). wf-recorder applies this on `AVCodecContext.gop_size` (`-p gop_size` is not a VAAPI private option). GOP 15 emptied a 0.25 s HRD four times a second. |
| `vaapiAsyncDepth` | `2` | Pipe `async_depth` (from profile). |
| `sinkScales` | `{}` | Per-sink Extend scale, keyed by MAC (overrides default) |
| `defaultExtendScale` | `1` | Extend scale when a sink has no `sinkScales` entry — **1** is cheapest for Hyprland |
| `onlyExpandFocusedDisplay` | `true` | Display panel accordion: only the **focused** output expands nested controls |

### Display panel expansion

By default every enabled display row is expanded (Brightness / Scale / cast
controls). To restore single-row accordion behavior:

```json
"onlyExpandFocusedDisplay": true
```

While connected, **WITH A MIRACAST DISPLAY** (under **WITH AN EXTERNAL DISPLAY**)
has Extend / Mirror. Place the Extend head on the **ARRANGEMENT** canvas (drag
the wifi tile left or right of the laptop; **h**/**l** with that tile selected).
Double-click the wifi tile for scale/rotation plus stream/encode/radio.
The **MIRACAST** row is a single line (summary + Scan / Doctor / Info / Start-Stop).
Only the focused
display row expands nested brightness/scale/cast controls.

### RENDER ENGINE

Shown only after the Miracast display exists (connected session). Default is
**GPU + DMA-BUF**. Pills (two lines — title + card-reported GPU name):

| Pill | `captureEncode` | Path |
|------|-----------------|------|
| GPU + DMA-BUF | `dmabuf` | `wf-recorder` DMA-BUF encode when VAAPI DMA works; else falls back to GPU pipe → CPU |
| GPU | `vaapi` | Hardware pipe: VAAPI / NVENC / QSV as probed |
| CPU | `cpu` | raw pipe → `libx264` |

```bash
miracast-ctl set-render-engine dmabuf|vaapi|cpu
# aliases: gpu-dmabuf | gpu | cpu
miracast-ctl gpu-info   # JSON: card-reported deviceName, vendor, dmabufLikely, …
```

Preference is stored in `settings.json` and `$XDG_STATE_HOME/omarchy-miracast/capture-encode`.
Changing engine **retargets** the current **QUALITY** tier (same label, different
knobs). Live knob changes while streaming usually apply via `restart-capture`
(SIGUSR1). If a GPU path fails, FluxCast falls back toward CPU; the **active**
pill follows the resolved path (`capturePath` / `encoder` in status).

### Interactive encode (WFD)

Aligned with [Wi-Fi Display](https://www.wi-fi.org/system/files/Miracast_Specification_v2.3.pdf)
§4.10.3 (adapt bitrate to the P2P link), [MS-WFDPE](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wfdpe/9ac9b0a4-0a94-483d-a8bf-cd7bfea99be0)
interactive latency, and AOSP `Converter.cpp` (**CBR**, ~1 s IDR).

| Knob | Interactive profile (kenya / hotyeah) | Why |
|------|----------------------------------------|-----|
| RC | **CBR** (`h264_vaapi`) | AOSP CBR. Intel QVBR undershoots (~0.2 Mbps) so a 3.5 Mbit VBV becomes seconds of lag. |
| HRD | **0.25 s** of target (`bufsize ≈ bitrate/4`) | Intel low-delay AVC. 0.1 s pumped quality on iHD. |
| GOP | **60** at 1080p60 | AOSP-style 1 s IDR. wf-recorder must set `AVCodecContext.gop_size` or Intel uses ~2 s. |
| `i_qfactor` | **1.0** | IDR same quantizer as P (no “refresh” flash). |
| AU delimiter | `aud=1` | Helps MPEG-TS access-unit framing. |
| Mux | DMA encode + ffmpeg **copy**; **no `aresample=async`** | That filter held ~0.5 s. |
| Audio | **LPCM `0x83`** if the sink lists LPCM; else AAC | WFD + AOSP LPCM PES. LPCM-only dongles ignore AAC. |
| HEADLESS Hz | Match negotiated fps; clamp to advertised modes (**60** typical) | 30 Hz on a 60 Hz-only head stalls ICC. |
| DMA freeze recovery | `encode stall` stderr (~4 s) + LPCM `wchar` IO watchdog (~8 s) | ICC DMA can stall after a window move; rchar stays flat so the watchdog watches wchar. |

Layout: packer includes the Miracast tile. `positionsToLua` stages physical outputs **past** the virtual head, then moves `persistent-miracast`, then lands eDP — otherwise Hyprland warns **monitor layout overlaps**. `place-virtual-head` on **x,y-only** does not SIGUSR1 capture (`wf-recorder -o` follows the output name). Do not `miracast-ctl stop`/`start` to tweak encode (that modesets the virtual head; on kenya it has corrupted eDP). Use `restart-capture` or a user-requested reconnect.

### PRESET QUALITY

Independent of render engine: **Best (Dynamic)** / **Very High** / **High** /
**Medium** / **Low**. Knobs are per engine in `scripts/encode_quality_presets.py`
(DMA-BUF high ≠ GPU-pipe high). Open the wifi tile **properties** (double-click or **I**).

```bash
miracast-ctl set-quality best|veryhigh|high|medium|low
miracast-ctl set-quality-effective step:N   # Best fine-step only
```

`castPreset` (`desktop` / `movie`) only toggles damage-aware vs continuous `-D`.

**Capture cadence:** Miracast Extend defaults to **damage-aware** capture
(omit `wf-recorder -D`) so Hyprland only produces frames when the output
changes — lower CPU, cursor still smooth. Force continuous grab with
`FLUXCAST_WFD_WF_RECORDER_DAMAGE=0`.

**Optional ICC wf-recorder (PR #347):** not required. Default is the distro
`wf-recorder` on `PATH` (wlr-screencopy). To opt into a local ICC build until
upstream ships it, set an absolute path explicitly:

```json
"wfRecorderBin": "/usr/local/bin/wf-recorder-icc",
"wfRecorderProto": "auto"
```

Or export `FLUXCAST_WFD_WF_RECORDER_BIN` / `FLUXCAST_WFD_WF_RECORDER_PROTO`
before connect. Env wins over settings. There is **no** automatic probing of
`~/src/...` build trees. If `wfRecorderProto` is `icc` but the binary is missing
or not ICC-capable, Miracast falls back to PATH stock and logs a warning.
See FluxCast `DOCUMENTATION.md`.

To score [BENCHMARKS.md](BENCHMARKS.md) results into settings (`captureEncode`,
`wfRecorderBin` / `Proto` / `Damage`, `videoEncoder`):

```bash
./scripts/recommend-cast-profile.py          # dry-run + docs/benchmarks/recommended.env
./scripts/recommend-cast-profile.py --apply  # update settings.json
miracast-ctl set-render-engine dmabuf|vaapi|cpu   # RENDER ENGINE (alias: set-capture-encode)
miracast-ctl set-quality high|medium|low          # QUALITY tier per engine (alias: set-encode-profile)
miracast-ctl set-cast-preset movie|desktop        # damage-aware vs continuous -D
miracast-ctl benchmark all                        # live matrix: every engine × every QUALITY tier
miracast-ctl benchmark --engines dmabuf,vaapi --tiers high,medium
# If already casting, matrix mode counts down 10s (Ctrl+C cancels; -y skips)
```

See [BENCHMARKS.md](BENCHMARKS.md) for presets and Intel CBR undershoot notes.
FluxCast auto-rebinds capture on buffer-pool / DTS spikes (RTSP stays up).

While connected, Hyprland **animations** are turned off and restored on stop.
Borders/gaps stay on so focus rings and the workspace indicator keep working.
Software cursors stay on (required for a visible pointer in screencopy).

**Extend scale:** default is `1` (`defaultExtendScale`) for lower Hyprland cost;
override per sink in the Display panel (`sinkScales`).

```bash
miracast-ctl benchmark                      # probes + live sample if streaming
miracast-ctl benchmark --offline-only       # capability-only (no live sample)
miracast-ctl benchmark --apply              # write settings.json + recommended-cast.env
miracast-ctl set-render-engine dmabuf|vaapi|cpu
miracast-ctl list-p2p-radios                # Auto / iface + P2P-GO / STA flags
miracast-ctl set-p2p-wifi-interface auto|IFACE
miracast-ctl pick-channel                   # scored quiet/quietest (default 5 GHz)
miracast-ctl pick-channel --band 2.4 --json
./scripts/bench_p2p_channel.sh              # SCC vs MCC TX A/B
```

`benchmark` probes VAAPI/`wf-recorder` support and P2P-GO radios, merges
`docs/benchmarks/results.tsv` when present, and — if a cast is already
streaming — runs a ~25s live TX/retry/CPU sample to refine the advice.
Use `--offline-only` to skip the live sample. `--apply` writes settings
(once per machine, or after adding a USB Wi‑Fi dongle).

### P2P channel (SCC vs quiet CSA)

By default Miracast uses **SCC**: force the P2P GO onto the **STA primary
channel** (`p2p_ignore_shared_freq=0`, `--wfd-p2p-channel=<STA>`), and after
PLAY align with CSA if negotiation landed elsewhere. Set `p2pQuietCsa: true`
(or `MIRACAST_P2P_QUIET_CSA=1`) to CSA onto a quieter channel instead (MCC).
If STA is 5 GHz but the sink’s **operating** channel stays on 2.4, cross-band
CSA is skipped and a quieter **2.4** channel is used instead. Some 8192CU-class
dongles still accept **5 GHz `oper_freq`** even when `listen_freq` is 2.4 —
verify with `./scripts/verify_p2p_air_band.py` (`p2pFreqSource=peer_oper`).
True 2.4-only oper → **MCC** (STA 5 GHz + P2P 2.4): known Miracast quality tax
(Microsoft eCSA / ScreenBeam “DCM”); expect occasional glitches. Mitigate with
quiet-channel pick + bitrate headroom, or a dual-band sink / second Wi‑Fi NIC.

**How “quiet” channel picking works** (`scripts/pick-p2p-channel.py`): the
label *quiet* is only a score threshold (default ≤ 5). What actually ranks
channels is a numeric **interference score** (lower is better): visible APs
from `nmcli` add cost on their channel and bleed into neighbors; stronger APs
cost more. When nothing is under the threshold (typical on 2.4 GHz), the
picker chooses the **lowest score** (“quietest”). That ranking is what
matters — and it has matched real Miracast **TX retry** rates on-device
(2026-09-15, AX201 + 2.4-only dongle: among `{1,6,11}`, ch 11 best / fewest
retries, ch 1 worst because the home 2.4 AP and strong adjacent BSS sit
there). Inspect scores with:

```bash
./scripts/pick-p2p-channel.py --json --band 2.4
miracast-ctl pick-channel
```

Developer wiring (CSA commands, tests) lives in [BUILD.md](BUILD.md) § P2P
channel.

**While streaming**, `scripts/miracast_link_watch.py` (started after PLAY) watches
the link cheaply: sysfs TX bytes every ~8s, `iw station dump` every few ticks,
and a **cached** `nmcli wifi list` score at most every ~3 minutes and only after
sustained high retries / IDR bursts (sink `wfd_idr_request` ≥2/tick is
decoder stall → QVBR drop, not iw-retry LOSS). Stall (TX &lt; ~3 Mbps for ~24s — often a
wedged VAAPI pipe) → `restart-capture`. A clearly better 2.4 GHz score can CSA
(5 min cooldown, max 2/hour, score margin). No forced Wi‑Fi rescans on the hot
path.

## Virtual output lifecycle (eDP safety)

Miracast **must not** call `hyprctl output remove` / `monitor,disable` during
connect or disconnect — those calls have frozen the primary display for
30–90s. Stop leaves the virtual output in place (`persistent-miracast`, often
parked at `-12000x0`); the next Extend session **reuses** it. Orphan cleanup
is never automatic on the hot path. Heads clear on Hyprland restart.

**Disconnected session cleanup.** When nothing is casting and no P2P group is
up, `miracast-ctl status` reconciles: stale `error`/connecting → `idle`, reap
watchers, drop parked-tracking files if the head is already gone, and re-park
an on-layout idle Extend head off-layout. It does **not** destroy the head.
Idle polls also skip `wpa_cli p2p_peer` for `lastPeerMac` so a dead sink does
not keep privileged Wi‑Fi probes forever.

**Hardware cursor plane.** Keep `cursor:no_hardware_cursors=true` while any
virtual head exists (live or parked). Restoring the HW cursor plane in the
same window as an eDP modeset has hard-locked i915 (no VT, caps-lock LED
stuck). `miracast-ctl` already holds software cursors for that lifetime; do
not toggle the option by hand to “fix” a missing pointer.

**Inactive VT / DRM master.** Hyprland on TTY1 does not own DRM while another
VT is active. `hyprctl dispatch` / `eval` that touches cursor, renderer, or
outputs (`force_renderer_reload`, `omarchy restart shell`, focus/warp onto
eDP, `no_hardware_cursors` changes) queues KMS work that applies when the
session regains master. Switching back (`Ctrl+Alt+F1`) has hard-locked i915
the same way — CPU may keep running; display and input die; there is often
no `GPU hang` printk. On kenya, short power is ignored
(`HandlePowerKey=ignore`); hold the power key.

**Lost laptop pointer** with a parked head is usually the cursor on that
head (check `hyprctl -j cursorpos` / focused monitor), not a hung eDP panel.
`warp_on_change_workspace=1` focusing `ext-*` is enough to put it there.

**Recovery**

| Situation | Do | Do not |
|-----------|----|--------|
| Still on the graphical session, pointer on the parked head | `hyprctl` focus/cursor warp onto eDP only | `output remove`, `monitor,disable`, `force_renderer_reload`, bounce `no_hardware_cursors`, `omarchy restart shell` |
| Already on another VT (TTY2, …) | Leave Hyprland alone. Reboot if you need the laptop. | Any of the above, then `Ctrl+Alt+F1` back |

Read-only `hyprctl monitors` / `cursorpos` / `layers` is fine from any VT.

## Cast modes

| Mode | Behavior |
|------|----------|
| **Mirror** | Captures the current desktop monitor |
| **Extend** | Creates a Hyprland virtual output beside the laptop and casts that |

## Shortcuts (Display panel)

| Key | Action |
|-----|--------|
| S | Scan sinks |
| D | Doctor (diagnose; open UFW ports if needed) |
| I | Miracast help (themed card; CLI uses terminal) |
| C | Connect last device / reconnect |
| X | Stop cast |
| M | Mirror mode |
| E | Extend mode |

## License

MIT — see [LICENSE](LICENSE).
