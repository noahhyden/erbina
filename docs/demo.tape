# VHS tape for the erbina README demo.
# Regenerate with:  scripts/record_demo.sh   (sets up the work dir, renders this
# tape, then crops the footer + collapses dead-air with ffmpeg). Run from repo root.
#
# erbina has no CLI — it is an MCP server you drive by asking Claude. So this
# records a REAL interactive Claude Code session: one prompt, and the agent
# inspects the recipe (shows the plan) then bootstraps + verifies the tool for
# real through erbina's MCP tools. We show the interactive TUI (the plan table,
# the streamed tool calls + answer) because that IS the product surface.
#
# Chrome-trimming: the interactive TUI opens on a welcome box + a plan-promo
# banner, and its footer shows account usage stats — all noise for a public
# asset. So we launch, accept the folder-trust dialog, submit the prompt, and
# only Show once those have scrolled off (~19s after submit; measured), landing
# on the clean plan-table -> bootstrap -> verified payoff. record_demo.sh then
# crops the bottom footer (usage stats) off entirely.
#
# Setup expected beforehand (scripts/record_demo.sh does all of it):
#   - vhs + ttyd + ffmpeg on PATH; ~/go/bin and ~/.local/bin on PATH
#   - a work dir at ~/.cache/erbina-demo with erbina.mcp.json -> server.py
#   - the demo tool (httpie) NOT yet installed, so the install actually runs
# `--allowedTools` pre-approves erbina's two tools so the run is deterministic
# (no permission prompts mid-record); the "consent surface" is inspect_recipe's
# plan, which the prompt explicitly asks for. `2>/dev/null` drops warnings this
# machine's global settings.json prints — noise unrelated to erbina.

Output docs/.demo-raw.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 800
Set Padding 20
Set TypingSpeed 35ms
Set Framerate 24

# --- hidden: launch the TUI, clear the first-run folder-trust dialog (a
#     harmless no-op once the dir is already trusted), let the MCP server
#     cold-start, submit the prompt, and wait for the welcome box + promo banner
#     to scroll off as the plan renders — so the frame opens clean. ---
Hide
Type "export PATH=$HOME/go/bin:$HOME/.local/bin:$PATH PS1='$ '" Enter
Type "cd $HOME/.cache/erbina-demo" Enter
Type "clear" Enter
Type "claude --mcp-config erbina.mcp.json --strict-mcp-config --allowedTools mcp__erbina__inspect_recipe mcp__erbina__bootstrap 2>/dev/null" Enter
Sleep 4s
Enter
Sleep 9s
Type "with erbina, inspect the httpie recipe to show the plan, then bootstrap it to install and verify"
Sleep 800ms
Enter
Sleep 19s
Show

# From here the frame is clean: the plan table is up and bootstrap is running.
# Hold long enough to capture the verified answer (~30s runs); ffmpeg collapses
# the trailing static into a short hold on the payoff.
Sleep 32s
