"""Tests for scripts/winget_candidates.py — the winget-id harvester.

The harvester closes erbina's Windows-install gap: the generator already renders
a `winget` install/update method whenever a recipe_data.py row carries a `winget`
key, but almost no rows do. This tool resolves winget community-source
PackageIdentifiers for rows that lack one, tiered by confidence, and stages them
for review.

These tests build a REAL in-memory SQLite index with the winget source schema
(packages / commands2 / commands2_map) so both the SQL and the pure resolver are
exercised without a network round-trip. The resolver's confidence model is the
security-relevant surface — a wrong id silently installs the wrong software on a
user's machine — so the mutation-guard tests below pin each tier's boundary.
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

import winget_candidates as wc


# --------------------------------------------------------------------------- #
# fixtures: a real SQLite index matching the winget source2 schema
# --------------------------------------------------------------------------- #
def build_conn(packages: list[tuple], commands: dict[str, list[str]]) -> sqlite3.Connection:
    """packages: list of (id, name, moniker); commands: {command: [package_id, ...]}."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE packages (rowid INTEGER PRIMARY KEY, id TEXT, name TEXT, moniker TEXT)")
    conn.execute("CREATE TABLE commands2 (rowid INTEGER PRIMARY KEY, command TEXT)")
    conn.execute("CREATE TABLE commands2_map (command INTEGER, package INTEGER)")
    id_to_row: dict[str, int] = {}
    for i, (pid, name, moniker) in enumerate(packages, start=1):
        conn.execute("INSERT INTO packages (rowid, id, name, moniker) VALUES (?,?,?,?)",
                     (i, pid, name, moniker))
        id_to_row[pid] = i
    cmd_row = 0
    for cmd, pids in commands.items():
        cmd_row += 1
        conn.execute("INSERT INTO commands2 (rowid, command) VALUES (?,?)", (cmd_row, cmd))
        for pid in pids:
            conn.execute("INSERT INTO commands2_map (command, package) VALUES (?,?)",
                         (cmd_row, id_to_row[pid]))
    conn.commit()
    return conn


# Each package is crafted to isolate exactly one resolver path:
#   sharkdp.pastel      gh-id-exact target (beats the moniker false-positive)
#   Japplis.Pastel      moniker `pastel` false-positive (a different, wrong tool)
#   Zellij.Zellij       command-unique, no publisher corroboration -> medium
#   acme.watcli         command-unique WHERE publisher==owner but repo!=pkg -> high
#   BurntSushi.ripgrep.MSVC   moniker `rg`, publisher==owner -> high
#   Task.Task           moniker `task`, no gh -> low
#   orf.gpingx/Some.Othergp   ambiguous command `gp`, publisher disambiguates
#   orf.gping/Some.Othergping ambiguous command `gping`, no gh -> none
PACKAGES = [
    ("sharkdp.pastel", "pastel", None),
    ("Japplis.Pastel", "Japplis Pastel", "pastel"),
    ("Zellij.Zellij", "Zellij", None),
    ("acme.watcli", "wat", None),
    ("BurntSushi.ripgrep.MSVC", "RipGrep MSVC", "rg"),
    ("Task.Task", "Task", "task"),
    ("orf.gpingx", "gpingx", None),
    ("Some.Othergp", "other gp", None),
    ("orf.gping", "gping", None),
    ("Some.Othergping", "other gping", None),
]
COMMANDS = {
    "pastel": ["sharkdp.pastel"],
    "zellij": ["Zellij.Zellij"],
    "wat": ["acme.watcli"],
    "gp": ["orf.gpingx", "Some.Othergp"],
    "gping": ["orf.gping", "Some.Othergping"],
}


@pytest.fixture
def index():
    idx = wc.WingetIndex(build_conn(PACKAGES, COMMANDS))
    yield idx
    idx.close()


# --------------------------------------------------------------------------- #
# norm
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("RipGrep", "ripgrep"),
    ("dua-cli", "duacli"),
    ("Hugo.Hugo", "hugohugo"),
    ("  Spaces _ Under ", "spacesunder"),
    (None, ""),
    ("", ""),
])
def test_norm(raw, expected):
    assert wc.norm(raw) == expected


# --------------------------------------------------------------------------- #
# rows_missing_winget — truthy check, not just key presence
# --------------------------------------------------------------------------- #
def test_rows_missing_winget_treats_empty_string_as_missing():
    tools = [
        {"id": "a", "winget": "Pub.A"},   # present -> excluded
        {"id": "b"},                       # absent  -> included
        {"id": "c", "winget": ""},         # blank   -> included (mutation guard)
        {"id": "d", "winget": None},       # None    -> included
    ]
    assert [t["id"] for t in wc.rows_missing_winget(tools)] == ["b", "c", "d"]


# --------------------------------------------------------------------------- #
# index queries
# --------------------------------------------------------------------------- #
def test_by_command_case_insensitive(index):
    assert index.by_command("PASTEL")[0][0] == "sharkdp.pastel"


def test_by_moniker_case_insensitive(index):
    assert index.by_moniker("TASK")[0][0] == "Task.Task"


def test_by_id_case_insensitive(index):
    assert index.by_id("task.task")[0][0] == "Task.Task"


def test_queries_return_empty_for_unknown(index):
    assert index.by_command("nope") == []
    assert index.by_moniker("nope") == []
    assert index.by_id("nope") == []


# --------------------------------------------------------------------------- #
# resolve — the confidence tiers
# --------------------------------------------------------------------------- #
def test_gh_id_exact_is_high_and_beats_a_moniker_false_positive(index):
    # `pastel`'s moniker hit is the WRONG tool (Japplis.Pastel, a Windows color
    # picker). The gh-derived exact id must win and produce sharkdp.pastel HIGH.
    p = wc.resolve({"id": "pastel", "bin": "pastel", "gh": "sharkdp/pastel"}, index)
    assert p == {"id": "pastel", "winget": "sharkdp.pastel",
                 "package_name": "pastel", "confidence": "high", "matched_by": "gh-id-exact"}


def test_command_unique_plus_publisher_is_high(index):
    # gh acme/watool: no exact id `acme.watool`, but command `wat` maps uniquely to
    # acme.watcli whose publisher matches the gh owner -> HIGH cmd+publisher.
    p = wc.resolve({"id": "wat", "bin": "wat", "gh": "acme/watool"}, index)
    assert p["winget"] == "acme.watcli"
    assert p["confidence"] == "high"
    assert p["matched_by"] == "cmd+publisher"


def test_ambiguous_command_disambiguated_by_publisher_is_high(index):
    # command `gp` -> {orf.gpingx, Some.Othergp}; gh owner orf picks orf.gpingx.
    # (gh repo `gpingtool` has no exact id, so gh-id-exact deliberately misses.)
    p = wc.resolve({"id": "gp", "bin": "gp", "gh": "orf/gpingtool"}, index)
    assert p["winget"] == "orf.gpingx"
    assert p["confidence"] == "high"
    assert p["matched_by"] == "cmd+publisher"


def test_command_unique_without_publisher_is_medium(index):
    # zellij: unique command match, no gh corroboration -> medium (review).
    p = wc.resolve({"id": "zellij", "bin": "zellij"}, index)
    assert p == {"id": "zellij", "winget": "Zellij.Zellij",
                 "package_name": "Zellij", "confidence": "medium", "matched_by": "cmd-unique"}


def test_moniker_plus_publisher_is_high(index):
    # ripgrep resolves by moniker `rg`; publisher BurntSushi matches gh owner.
    p = wc.resolve({"id": "ripgrep", "bin": "rg", "gh": "BurntSushi/ripgrep"}, index)
    assert p["winget"] == "BurntSushi.ripgrep.MSVC"
    assert p["confidence"] == "high"
    assert p["matched_by"] == "moniker+publisher"


def test_moniker_only_is_low(index):
    # `task` resolves by moniker with no gh corroboration -> low.
    p = wc.resolve({"id": "task", "bin": "task"}, index)
    assert p["winget"] == "Task.Task"
    assert p["confidence"] == "low"
    assert p["matched_by"] == "moniker-only"


def test_ambiguous_command_without_disambiguation_is_none(index):
    # gping is ambiguous by command and there's no gh owner to disambiguate.
    assert wc.resolve({"id": "gping", "bin": "gping"}, index) is None


def test_no_match_is_none(index):
    assert wc.resolve({"id": "nonesuch", "bin": "nonesuch"}, index) is None


# --- mutation guards on the confidence boundaries ------------------------- #
def test_publisher_match_is_normalized_equality_not_substring(index):
    # gh owner "or" must NOT be treated as matching publisher "orf" (substring),
    # so the ambiguous command `gp` stays unresolved -> None.
    assert wc.resolve({"id": "gp", "bin": "gp", "gh": "or/gpingtool"}, index) is None


def test_gh_id_exact_requires_full_owner_and_repo(index):
    # A gh with no slash must not crash and must not fabricate an id — it should
    # fall through to the command tier (medium), proving gh parsing was safe.
    p = wc.resolve({"id": "zellij", "bin": "zellij", "gh": "noslash"}, index)
    assert p["confidence"] == "medium"


# --------------------------------------------------------------------------- #
# resolve_all — threshold filtering and ordering
# --------------------------------------------------------------------------- #
def test_resolve_all_respects_min_confidence(index):
    tools = [
        {"id": "pastel", "bin": "pastel", "gh": "sharkdp/pastel"},  # high
        {"id": "zellij", "bin": "zellij"},                          # medium
        {"id": "task", "bin": "task"},                              # low
        {"id": "ghost", "bin": "ghost"},                            # none
    ]
    high = wc.resolve_all(tools, index, min_confidence="high")
    assert [p["id"] for p in high] == ["pastel"]

    med = wc.resolve_all(tools, index, min_confidence="medium")
    assert [p["id"] for p in med] == ["pastel", "zellij"]  # sorted by id

    low = wc.resolve_all(tools, index, min_confidence="low")
    assert [p["id"] for p in low] == ["pastel", "task", "zellij"]


def test_resolve_all_skips_rows_that_already_have_winget(index):
    tools = [
        {"id": "zellij", "bin": "zellij", "winget": "Zellij.Zellij"},  # already set
        {"id": "task", "bin": "task"},
    ]
    got = wc.resolve_all(tools, index, min_confidence="low")
    assert [p["id"] for p in got] == ["task"]


def test_resolve_all_id_filter(index):
    tools = [{"id": "zellij", "bin": "zellij"}, {"id": "task", "bin": "task"}]
    got = wc.resolve_all(tools, index, min_confidence="low", ids={"task"})
    assert [p["id"] for p in got] == ["task"]


# --------------------------------------------------------------------------- #
# apply_proposals — staging into recipe_data.py source text (pure)
# --------------------------------------------------------------------------- #
SRC = (
    'TOOLS = [\n'
    '    {"id": "fd", "bin": "fd", "brew": "fd", "gh": "sharkdp/fd"},\n'
    '    {"id": "fdupes", "bin": "fdupes", "brew": "fdupes"},\n'
    '    {"id": "rg", "bin": "rg", "winget": "BurntSushi.ripgrep.MSVC"},\n'
    ']\n'
)


def test_apply_inserts_after_id_and_is_anchored_to_exact_id():
    proposals = [{"id": "fd", "winget": "sharkdp.fd"}]
    new, applied, missing = wc.apply_proposals(SRC, proposals)
    assert applied == ["fd"]
    assert missing == []
    # inserted on the fd row only, right after its id...
    assert '{"id": "fd", "winget": "sharkdp.fd", "bin": "fd"' in new
    # ...and NOT on the fdupes row (mutation guard: exact-id anchoring).
    assert '"id": "fdupes", "winget"' not in new


def test_apply_is_idempotent_on_rows_that_already_have_winget():
    proposals = [{"id": "rg", "winget": "Something.Else"}]
    new, applied, missing = wc.apply_proposals(SRC, proposals)
    assert applied == []           # already had winget -> untouched
    assert new == SRC


def test_apply_reports_missing_ids():
    proposals = [{"id": "ghost", "winget": "No.Body"}]
    new, applied, missing = wc.apply_proposals(SRC, proposals)
    assert applied == []
    assert missing == ["ghost"]
    assert new == SRC


def test_apply_multiple_and_result_is_valid_python():
    proposals = [{"id": "fd", "winget": "sharkdp.fd"}, {"id": "fdupes", "winget": "Adrian.fdupes"}]
    new, applied, missing = wc.apply_proposals(SRC, proposals)
    assert sorted(applied) == ["fd", "fdupes"]
    ns: dict = {}
    exec(new, ns)  # noqa: S102 - trusted fixture, proves output parses
    tools = {t["id"]: t.get("winget") for t in ns["TOOLS"]}
    assert tools == {"fd": "sharkdp.fd", "fdupes": "Adrian.fdupes", "rg": "BurntSushi.ripgrep.MSVC"}


# --------------------------------------------------------------------------- #
# WingetIndex.from_msix — extract Public/index.db out of a msix (zip)
# --------------------------------------------------------------------------- #
def _make_msix(tmp_path: Path) -> Path:
    conn = build_conn([("Zellij.Zellij", "Zellij", None)], {"zellij": ["Zellij.Zellij"]})
    dbfile = tmp_path / "src.db"
    disk = sqlite3.connect(dbfile)
    conn.backup(disk)
    disk.close()
    conn.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Public/index.db", dbfile.read_bytes())
    msix = tmp_path / "source.msix"
    msix.write_bytes(buf.getvalue())
    return msix


def test_from_msix_extracts_and_queries(tmp_path):
    idx = wc.WingetIndex.from_msix(_make_msix(tmp_path))
    try:
        assert idx.by_command("zellij")[0][0] == "Zellij.Zellij"
    finally:
        idx.close()


# --------------------------------------------------------------------------- #
# main — end-to-end against a fixture msix + fixture recipe_data.py
# --------------------------------------------------------------------------- #
def _fixture_recipe_data(tmp_path: Path) -> Path:
    p = tmp_path / "recipe_data.py"
    p.write_text(
        'from __future__ import annotations\n'
        'TOOLS: list[dict] = [\n'
        '    {"id": "zellij", "bin": "zellij", "brew": "zellij"},\n'
        '    {"id": "ghost", "bin": "ghost", "brew": "ghost"},\n'
        ']\n'
    )
    return p


def test_main_writes_proposals_json(tmp_path):
    out = tmp_path / "proposals.json"
    rc = wc.main([
        "--msix", str(_make_msix(tmp_path)),
        "--recipe-data", str(_fixture_recipe_data(tmp_path)),
        "--out", str(out),
        "--min-confidence", "medium",
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert [p["id"] for p in data] == ["zellij"]
    assert data[0]["winget"] == "Zellij.Zellij"


def test_main_apply_writes_winget_key_into_recipe_data(tmp_path):
    rd = _fixture_recipe_data(tmp_path)
    rc = wc.main([
        "--msix", str(_make_msix(tmp_path)),
        "--recipe-data", str(rd),
        "--out", str(tmp_path / "p.json"),
        "--min-confidence", "medium",
        "--apply",
    ])
    assert rc == 0
    ns: dict = {}
    exec(rd.read_text(), ns)  # noqa: S102 - reads what main wrote back
    winget = {t["id"]: t.get("winget") for t in ns["TOOLS"]}
    assert winget == {"zellij": "Zellij.Zellij", "ghost": None}
