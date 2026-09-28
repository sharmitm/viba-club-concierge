"""Spec traceability: specs/ and tests/ must agree.

Fails when an `enforced` requirement has no tagged test, or a test is tagged
with an ID no spec defines. Run as a module to print the full matrix:

    python -m tests.test_spec_traceability
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"
TESTS = ROOT / "tests"

_HEADING = re.compile(r"^### ([A-Z]{2}-\d{2}) (.+)$")
_STATUS = re.compile(r"^\*\*Status\.\*\* (\w+)")


def load_requirements() -> dict[str, dict]:
    """{id: {"title", "status", "file"}} parsed from specs/*.md."""
    reqs: dict[str, dict] = {}
    for path in sorted(SPECS.glob("*.md")):
        if path.name == "README.md":   # format guide, holds an example heading
            continue
        current = None
        for line in path.read_text().splitlines():
            if m := _HEADING.match(line):
                current = m.group(1)
                assert current not in reqs, f"duplicate requirement id {current}"
                reqs[current] = {"title": m.group(2), "status": None, "file": path.name}
            elif current and (m := _STATUS.match(line)):
                reqs[current]["status"] = m.group(1)
    return reqs


def load_links() -> dict[str, list[str]]:
    """{id: ["file::test", ...]} from @pytest.mark.spec(...) decorators."""
    links: dict[str, list[str]] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef):
                continue
            for deco in node.decorator_list:
                if (isinstance(deco, ast.Call)
                        and ast.unparse(deco.func) == "pytest.mark.spec"):
                    for arg in deco.args:
                        links.setdefault(arg.value, []).append(f"{path.name}::{node.name}")
    return links


def test_every_requirement_has_a_status():
    missing = [rid for rid, r in load_requirements().items()
               if r["status"] not in {"enforced", "planned", "retired"}]
    assert not missing, f"requirements without a valid **Status.** line: {missing}"


def test_every_enforced_requirement_is_tested():
    links = load_links()
    untested = [f"{rid} ({r['file']}: {r['title']})"
                for rid, r in load_requirements().items()
                if r["status"] == "enforced" and rid not in links]
    assert not untested, "enforced requirements with no @pytest.mark.spec test:\n  " + \
        "\n  ".join(untested)


def test_every_spec_tag_points_at_a_live_requirement():
    reqs = load_requirements()
    dangling = {rid: tests for rid, tests in load_links().items()
                if rid not in reqs or reqs[rid]["status"] == "retired"}
    assert not dangling, f"tests tagged with unknown or retired requirement ids: {dangling}"


if __name__ == "__main__":
    reqs, links = load_requirements(), load_links()
    for rid, r in reqs.items():
        tests = links.get(rid, [])
        mark = "ok " if tests or r["status"] != "enforced" else "GAP"
        print(f"{mark} {rid} [{r['status']}] {r['title']}")
        for t in tests:
            print(f"      - {t}")
