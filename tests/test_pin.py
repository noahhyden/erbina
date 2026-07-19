"""Tests for pinning (phase 3b): the `pin` tool and how check_updates / update
honor pins. State is isolated to a temp dir by the autouse conftest fixture.
"""
from __future__ import annotations

import server
from helpers import call_tool
from prototype import TRUE, cli_recipe, registry


def _versioned(rid="t", current="1.0.0", latest="2.0.0"):
    return cli_recipe(
        rid,
        detect={"command": TRUE},
        version={"current": f"echo {current}", "latest": f"echo {latest}"},
        update={"methods": [{"id": "u", "run": TRUE}]},
        verify=[{"command": TRUE}],
    )


# --------------------------------------------------------------------------- #
# the pin tool
# --------------------------------------------------------------------------- #
def test_pin_sets_flag_in_state():
    with registry(cli_recipe("t")):
        out = call_tool("pin", {"recipe_id": "t"})
    assert out["pinned"] is True
    assert server._read_state()["tools"]["t"]["pinned"] is True
    assert server._is_pinned("t") is True


def test_unpin_clears_flag():
    with registry(cli_recipe("t")):
        call_tool("pin", {"recipe_id": "t"})
        out = call_tool("pin", {"recipe_id": "t", "pinned": False})
    assert out["pinned"] is False
    assert server._is_pinned("t") is False


def test_pin_unknown_recipe_errors():
    with registry(cli_recipe("t")):
        out = call_tool("pin", {"recipe_id": "ghost"})
    assert "error" in out
    assert "no recipe" in out["error"]


def test_pin_does_not_clobber_existing_record():
    # pinning a tool erbina already recorded must keep its version/method
    with registry(_versioned("t")):
        call_tool("bootstrap", {"recipe_id": "t"})  # records install_method etc.
        call_tool("pin", {"recipe_id": "t"})
    rec = server._read_state()["tools"]["t"]
    assert rec["pinned"] is True
    assert "install_method" in rec  # earlier recording survived


# --------------------------------------------------------------------------- #
# check_updates honors pins
# --------------------------------------------------------------------------- #
def test_check_updates_excludes_pinned_from_updates_available():
    with registry(_versioned("t", current="1.0.0", latest="2.0.0")):
        call_tool("pin", {"recipe_id": "t"})
        out = call_tool("check_updates", {"recipe_id": "t"})
    entry = out["checked"][0]
    assert entry["pinned"] is True
    assert entry["update_available"] is True   # a newer version DOES exist
    assert out["updates_available"] == []      # but it's not offered
    assert "Pinned" in out["hint"]


def test_check_updates_includes_unpinned_update():
    with registry(_versioned("t", current="1.0.0", latest="2.0.0")):
        out = call_tool("check_updates", {"recipe_id": "t"})
    assert out["checked"][0]["pinned"] is False
    assert out["updates_available"] == ["t"]


def test_pinned_but_current_tool_is_not_reported_as_skipped():
    # a pinned tool with NO newer version must NOT show up in the
    # "Pinned (skipped despite an update)" hint — that hint is only for a pin
    # that actually hides an available update. (mutation guard: pinned_with_update
    # is update_available AND pinned, not OR.)
    with registry(_versioned("t", current="1.0.0", latest="1.0.0")):
        call_tool("pin", {"recipe_id": "t"})
        out = call_tool("check_updates", {"recipe_id": "t"})
    entry = out["checked"][0]
    assert entry["pinned"] is True
    assert entry["update_available"] is False       # already current
    assert out["updates_available"] == []
    assert "Pinned (skipped" not in out["hint"]     # nothing was skipped


# --------------------------------------------------------------------------- #
# update honors pins
# --------------------------------------------------------------------------- #
def test_update_refuses_pinned_tool():
    with registry(_versioned("t")):
        call_tool("pin", {"recipe_id": "t"})
        out = call_tool("update", {"recipe_id": "t"})
    assert out.get("skipped") is True
    assert out["pinned"] is True
    assert "phases" not in out  # never ran

def test_update_force_overrides_a_pin():
    with registry(_versioned("t")):
        call_tool("pin", {"recipe_id": "t"})
        out = call_tool("update", {"recipe_id": "t", "force": True})
    assert out.get("skipped") is not True
    assert out["ok"] is True
    assert out["phases"]["update"]["status"] == "ok"


def test_update_unpinned_proceeds_normally():
    with registry(_versioned("t")):
        out = call_tool("update", {"recipe_id": "t"})
    assert out["ok"] is True
    assert out["phases"]["update"]["status"] == "ok"
