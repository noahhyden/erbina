#!/usr/bin/env bash
# Regenerate docs/demo.gif — the README demo of Claude driving erbina.
#
# erbina has no CLI, so the demo is a REAL `claude -p` session (see docs/demo.tape).
# VHS records it; the model's "thinking" span shows as a static terminal, so we
# then run ffmpeg mpdecimate to drop the duplicate (idle) frames and hold the
# final answer for a beat. Requires: vhs, ffmpeg, and the `claude` CLI on PATH,
# plus ~/go/bin and ~/.local/bin (where go/pipx tools land).
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/go/bin:$HOME/.local/bin:$PATH"

RAW=docs/.demo-raw.gif
OUT=docs/demo.gif

# fresh state so the install actually runs in the recording
pipx uninstall httpie >/dev/null 2>&1 || true

echo "recording $RAW via vhs…"
vhs docs/demo.tape

echo "collapsing idle frames + holding the final answer → $OUT…"
ffmpeg -y -i "$RAW" \
  -vf "mpdecimate,setpts=N/FRAME_RATE/TB,tpad=stop_mode=clone:stop_duration=3,fps=24,split[s0][s1];[s0]palettegen=stats_mode=full[p];[s1][p]paletteuse=dither=bayer" \
  "$OUT"

rm -f "$RAW"
echo "done: $OUT ($(du -h "$OUT" | cut -f1))"
