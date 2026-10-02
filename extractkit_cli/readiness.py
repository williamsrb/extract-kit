"""Target readiness: is the legacy checkout indexed for the agent tools.

The kit never runs Serena, Graphify or graft. It only looks for what they leave
behind, and names the command that produces it.
"""

from __future__ import annotations

from pathlib import Path

from .common import Row

SERENA_FIX = "open an agent session in {source} (not in the kit) and run Serena onboarding"
GRAPHIFY_FIX = "in an agent session opened in {source}, build a Graphify index (the graphify skill, for example `/graphify .`)"
GRAFT_FIX = "run `graft build` in {source}"


def check_source(source: Path) -> list[Row]:
    """Serena and Graphify must be present; a missing graft index only warns."""
    return [_serena(source), _graphify(source), _graft(source)]


def serena_pointer(source: Path) -> str | None:
    """Path to `.serena/` when onboarding has run, else None."""
    return str(source / ".serena") if _serena(source).state == "ok" else None


def _serena(source: Path) -> Row:
    root = source / ".serena"
    fix = SERENA_FIX.format(source=source)
    if not (root / "project.yml").is_file():
        return Row("serena onboarding", "MISSING", "no .serena/project.yml", fix, code="readiness_missing")
    if not any((root / "memories").glob("*.md")):
        return Row("serena onboarding", "MISSING", "no .serena/memories/*.md", fix, code="readiness_missing")
    return Row("serena onboarding", "ok", str(root))


def _graphify(source: Path) -> Row:
    graph = source / "graphify-out" / "graph.json"
    if graph.is_file():
        return Row("graphify index", "ok", str(graph))
    return Row(
        "graphify index", "MISSING", "no graphify-out/graph.json",
        GRAPHIFY_FIX.format(source=source), code="readiness_missing",
    )


def _graft(source: Path) -> Row:
    index = source / "graft"
    if index.is_dir():
        return Row("graft index", "ok", str(index))
    return Row(
        "graft index", "warn", "no graft/ index (map.code will skip)",
        GRAFT_FIX.format(source=source), required=False,
    )
