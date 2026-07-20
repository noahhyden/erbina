#!/usr/bin/env bash
# Regenerate docs/demo.gif — the README demo of Claude driving erbina.
#
# erbina has no CLI, so the demo is a REAL interactive Claude Code session (see
# docs/demo.tape). VHS records the TUI; this script then post-processes with
# ffmpeg: crop the account/usage footer off the bottom, speed the run up ~2x for
# a readable ~16s, and hold the verified answer for a beat. Requires: vhs,
# ffmpeg, and the `claude` CLI on PATH, plus ~/go/bin and ~/.local/bin (where
# go/pipx tools land).
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/go/bin:$HOME/.local/bin:$PATH"

REPO="$(pwd)"
WORKDIR="$HOME/.cache/erbina-demo"
RAW=docs/.demo-raw.gif
OUT=docs/demo.gif

# Reproducible work dir the tape drives: an erbina.mcp.json pointing at this
# checkout's server.py. (The tape accepts the first-run folder-trust dialog
# itself, so no global config is touched.)
echo "setting up work dir $WORKDIR…"
mkdir -p "$WORKDIR"
printf '{ "mcpServers": { "erbina": { "command": "uv", "args": ["run", "--script", "%s/server.py"] } } }\n' \
  "$REPO" > "$WORKDIR/erbina.mcp.json"

# fresh state so the install actually runs in the recording
pipx uninstall httpie >/dev/null 2>&1 || true

echo "recording $RAW via vhs…"
vhs docs/demo.tape

# Post-process: crop off the bottom footer (input box + account usage stats),
# scale down, speed up ~2x for readability, and pad a short hold on the final
# verified answer. 672px keeps all conversation content above the footer.
echo "cropping footer + speeding up + holding the answer → $OUT…"
ffmpeg -y -i "$RAW" \
  -vf "crop=1200:672:0:0,scale=960:-1:flags=lanczos,setpts=PTS/2,tpad=stop_mode=clone:stop_duration=2,fps=15,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=full[p];[s1][p]paletteuse=dither=bayer" \
  "$OUT"

rm -f "$RAW"
echo "done: $OUT ($(du -h "$OUT" | cut -f1))"
