#!/usr/bin/env bash
# Hold a native PipeWire echo-cancel module (monitor.mode) for the life of
# the cast. Client-loaded modules die when pw-cli disconnects, so this
# process stays attached. Capture = analog mic; reference = default-sink
# monitor (Miracast when that is the output). No extra user-facing sink.
set -euo pipefail
printf 'miracast-aec\n' >/proc/self/comm 2>/dev/null || true

MIC="${1:?analog mic node name}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-miracast"
LOG="${STATE}/logs/aec-holder.log"
FIFO="${STATE}/aec.pwcli"
mkdir -p "$STATE/logs"
rm -f "$FIFO"
mkfifo "$FIFO"
: >>"$LOG"

pw-cli -m <"$FIFO" >>"$LOG" 2>&1 &
pw=$!
echo "$pw" >"${STATE}/audio-aec.pwcli.pid"
cleanup() {
  exec 3>&- 2>/dev/null || true
  kill "$pw" 2>/dev/null || true
  sleep 0.1
  kill -9 "$pw" 2>/dev/null || true
  rm -f "$FIFO" "${STATE}/audio-aec.pwcli.pid"
}
trap cleanup EXIT INT TERM

exec 3>"$FIFO"
# One line; pw-cli reads a command per line.
# Capture streams keep media.class Stream/Input (hidden from the mic picker).
# The cancelled output must stay Audio/Source so it has ports; we do not set
# it as the default source, and we name it omarchy_speaker_tuning so it is
# not a user-facing "Echo-Cancel Source" label.
printf '%s\n' "load-module libpipewire-module-echo-cancel { monitor.mode = true capture.props = { node.name = \"omarchy_speaker_tuning.aec_cap\" node.virtual = true target.object = \"${MIC}\" } source.props = { node.name = \"omarchy_speaker_tuning.miracast_aec\" node.description = \"omarchy_speaker_tuning.miracast_aec\" node.nick = \"omarchy_speaker_tuning.miracast_aec\" media.class = \"Audio/Source\" node.virtual = true priority.session = 0 } aec.args = { webrtc.gain_control = false } }" >&3

# Keep the fifo writer open so pw-cli stays connected.
while kill -0 "$pw" 2>/dev/null; do
  sleep 30
done
