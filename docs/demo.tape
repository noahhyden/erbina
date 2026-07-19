# VHS tape for the erbina README demo.
# Regenerate with:  scripts/record_demo.sh   (renders this tape, then collapses
# the model's "thinking" dead-air with ffmpeg mpdecimate). Run from the repo root.
#
# erbina has no CLI — it is an MCP server you drive by asking Claude. So this
# records a REAL headless Claude Code session (`claude -p`): one prompt, and the
# agent inspects the recipe (the consent surface) then bootstraps + verifies the
# tool for real through erbina's MCP tools. `-p` keeps the frame clean (no TUI
# chrome / account status), which matters for a public asset.
#
# Setup expected beforehand (see scripts/record_demo.sh):
#   - vhs + ttyd + ffmpeg on PATH; ~/go/bin and ~/.local/bin on PATH
#   - a work dir with erbina.mcp.json pointing at server.py
#   - the demo tool (httpie) NOT yet installed, so the install actually runs
# `2>/dev/null` drops warnings this machine's global settings.json prints —
# noise unrelated to erbina that wouldn't appear on a clean install.

Output docs/.demo-raw.gif

Set Shell "bash"
Set FontSize 18
Set Width 1180
Set Height 700
Set Padding 26
Set TypingSpeed 40ms
Set Framerate 24

# --- hidden setup: PATH, clean prompt, demo dir ---
Hide
Type "export PATH=$HOME/go/bin:$HOME/.local/bin:$PATH PS1='$ '" Enter
Type "cd /tmp/claude-1000/-home-noahpimentel-repos-erbina/3b95f82d-c8a9-4b1e-89e2-810629670647/scratchpad/erbina-demo" Enter
Type "clear" Enter
Show

Sleep 700ms
Type "# erbina has no CLI — you drive it by asking Claude:" Enter
Sleep 1.2s

Type `claude -p "with erbina, inspect the httpie recipe to show the plan, then \` Enter
Type `bootstrap it to install and verify" \` Enter
Type "  --mcp-config erbina.mcp.json --strict-mcp-config \" Enter
Type "  --allowedTools mcp__erbina__inspect_recipe mcp__erbina__bootstrap 2>/dev/null"
Sleep 500ms
Enter

# real work: inspect_recipe (consent) -> bootstrap via pipx -> verify.
# the static "thinking" span here is collapsed by mpdecimate in record_demo.sh.
Sleep 34s
