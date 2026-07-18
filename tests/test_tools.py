"""Tool-surface tests, driven through the in-memory FastMCP client.

These exercise erbina exactly as an agent would (Client(server.mcp)) and assert
only on read-only / dry-run paths — nothing here installs, wires, or removes
anything.
"""
from __future__ import annotations

from helpers import call_tool, list_tool_names

EXPECTED_TOOLS = {
    "list_recipes",
    "inspect_recipe",
    "bootstrap",
    "check_updates",
    "update",
    "pin",
    "audit_scopes",
    "find_dead_mcps",
    "remove_mcp",
}


def test_exactly_expected_tools_register():
    assert list_tool_names() == EXPECTED_TOOLS


def test_list_recipes_includes_both_real_recipes():
    recipes = call_tool("list_recipes", {})
    ids = {r["id"] for r in recipes}
    assert "ataegina" in ids
    assert "fetch" in ids
    # sanity: the reported kinds match the shipped recipes
    by_id = {r["id"]: r for r in recipes}
    assert by_id["ataegina"]["kind"] == "cli-tool"
    assert by_id["fetch"]["kind"] == "mcp-server"


def test_inspect_recipe_returns_plan_without_executing():
    out = call_tool("inspect_recipe", {"recipe_id": "ataegina"})
    assert "error" not in out
    assert out["id"] == "ataegina"
    plan = out["will_run"]
    # The consent surface must name the detect + verify commands verbatim.
    assert plan["detect"] == "ataegina --version"
    assert "ataegina --version" in plan["verify"]
    # inspect_recipe never executes anything — it says so, and returns no
    # execution "phases" (that key only appears on a real bootstrap run).
    assert "Nothing was executed" in out["note"]
    assert "phases" not in out


def test_bootstrap_dry_run_returns_plan_and_runs_nothing():
    out = call_tool("bootstrap", {"recipe_id": "ataegina", "dry_run": True})
    assert "error" not in out
    assert out["dry_run"] is True
    # dry-run is reflected: nothing was executed, phases stayed empty.
    assert out["phases"] == {}
    assert "nothing executed" in out["note"].lower()
    plan = out["plan"]
    assert plan["detect"] == "ataegina --version"
    assert "ataegina --version" in plan["verify"]


def test_bootstrap_dry_run_substitutes_scope_for_mcp_server_recipe():
    # fetch is a mcp-server recipe whose configure step uses ${scope}.
    out = call_tool(
        "bootstrap",
        {"recipe_id": "fetch", "scope": "project", "dry_run": True, "project_dir": "/tmp/x"},
    )
    assert "error" not in out
    assert out["dry_run"] is True
    assert out["phases"] == {}
    cfg = out["plan"]["configure"]
    joined = " ".join(step["run"] for step in cfg)
    assert "--scope project" in joined
    assert "${scope}" not in joined


# --------------------------------------------------------------------------- #
# path traversal & bad input rejection
# --------------------------------------------------------------------------- #
def _tool_error(tool: str, recipe_id: str):
    """Call a load-path tool and return the surfaced error, whether it comes
    back as a FastMCP ToolError (raised) or an {'error': ...} payload."""
    try:
        out = call_tool(tool, {"recipe_id": recipe_id})
    except Exception as e:  # noqa: BLE001 - we want the message, whatever the type
        return str(e)
    if isinstance(out, dict) and "error" in out:
        return out["error"]
    return repr(out)


def test_inspect_recipe_rejects_dotdot_server_traversal():
    # ../server would reach server.py if traversal were possible; _load_recipe
    # collapses it to `server.yaml`, which does not exist -> "no recipe".
    msg = _tool_error("inspect_recipe", "../server")
    assert "no recipe" in msg.lower()
    # It must not have LOADED server.py — no server source leaks into the reply.
    assert "FastMCP" not in msg
    assert "import" not in msg


def test_bootstrap_rejects_etc_passwd_traversal():
    msg = _tool_error("bootstrap", "../../etc/passwd")
    assert "no recipe" in msg.lower()
    # The rejection may echo back the (safe) recipe_id, but it must not have
    # READ /etc/passwd — no file contents leak (e.g. the classic root: line).
    assert "root:" not in msg
    assert "/bin/" not in msg
    # available-recipes hint should list only real registry entries
    assert "ataegina" in msg or "fetch" in msg


def test_inspect_recipe_rejects_bad_scope():
    out = call_tool("inspect_recipe", {"recipe_id": "ataegina", "scope": "bogus"})
    assert isinstance(out, dict)
    assert "error" in out
    assert "scope must be one of" in out["error"]


def test_bootstrap_rejects_bad_scope():
    out = call_tool("bootstrap", {"recipe_id": "ataegina", "scope": "bogus", "dry_run": True})
    assert isinstance(out, dict)
    assert "error" in out
    assert "scope must be one of" in out["error"]
    # bad scope is rejected BEFORE any plan/exec work happens
    assert "phases" not in out
