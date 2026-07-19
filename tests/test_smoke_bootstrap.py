"""Offline plumbing test for scripts/smoke_bootstrap.py.

The smoke driver's JOB is to run real installs on CI, but its wiring — does it
drive bootstrap through the tool surface and report ok/failure correctly? — can
be validated deterministically here against prototype recipes (builtin commands,
no real install). This guards the driver against bit-rot without any network.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from prototype import FALSE, TRUE, cli_recipe, registry

_DRIVER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke_bootstrap.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location("smoke_bootstrap", _DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DRIVER = _load_driver()


def test_driver_reports_ok_for_a_healthy_recipe():
    r = cli_recipe("t", detect={"command": FALSE}, verify=[{"command": TRUE}])
    with registry(r):
        report = DRIVER._bootstrap("t")
    assert report["ok"] is True
    assert report["phases"]["install"]["status"] == "ok"


def test_driver_surfaces_a_failing_install():
    r = cli_recipe("t", detect={"command": FALSE},
                   install={"methods": [{"id": "x", "run": FALSE}]})
    with registry(r):
        report = DRIVER._bootstrap("t")
    assert report["ok"] is False


def test_driver_main_exit_code_reflects_failures(monkeypatch, capsys):
    good = cli_recipe("good", detect={"command": FALSE}, verify=[{"command": TRUE}])
    bad = cli_recipe("bad", detect={"command": FALSE},
                     install={"methods": [{"id": "x", "run": FALSE}]})
    with registry(good, bad):
        monkeypatch.setattr("sys.argv", ["smoke_bootstrap.py", "good", "bad"])
        rc = DRIVER.main()
    out = capsys.readouterr().out
    assert rc == 1                      # one recipe failed -> non-zero exit
    assert "FAILED to bootstrap: bad" in out


def test_driver_main_succeeds_when_all_ok(monkeypatch, capsys):
    a = cli_recipe("a", detect={"command": FALSE}, verify=[{"command": TRUE}])
    b = cli_recipe("b", detect={"command": TRUE})  # already present -> install skipped
    with registry(a, b):
        monkeypatch.setattr("sys.argv", ["smoke_bootstrap.py", "a", "b"])
        rc = DRIVER.main()
    assert rc == 0
    assert "bootstrapped 2 recipe(s) for real" in capsys.readouterr().out
