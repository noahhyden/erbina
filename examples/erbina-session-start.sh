#!/usr/bin/env bash
# erbina — OPT-IN SessionStart hook.
#
# This script does NOT run erbina (erbina is an MCP server with no CLI). It only
# prints a SessionStart hook payload whose `additionalContext` nudges the agent
# to call erbina's `check_updates` tool at the start of a session and surface any
# available tool updates for your confirmation. Nothing is installed or updated
# automatically.
#
# Enable it by pointing a SessionStart hook at this file — see AUTO_UPDATE.md
# ("Enabling automatic checks"). Remove the hook to turn it off.
cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "At the start of this session, call erbina's check_updates tool. If it reports any updates_available, tell the user which tools have updates (use the `summary`), and ask before applying anything with erbina's update tool. If nothing is available, stay silent."
  }
}
JSON
