"""map.semantic — point at an existing source graphify-out/. Never run graphify."""

from __future__ import annotations

from extractkit_cli.readiness import GRAPHIFY_FIX


class MapSemanticStep:
    id = "map.semantic"
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    required = False

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        source = ctx.source  # type: ignore[attr-defined]
        overlay = source / "graphify-out"
        if overlay.is_dir():
            ctx.map_pointers["semantic"] = str(overlay)  # type: ignore[attr-defined]
            ctx.plan.record(f"reuse semantic map {overlay}")  # type: ignore[attr-defined]
            return
        ctx.map_pointers["semantic"] = None  # type: ignore[attr-defined]
        ctx.record_skip(  # type: ignore[attr-defined]
            self.id,
            f"no graphify-out/ in {source}",
            GRAPHIFY_FIX.format(source=source),
        )

    def check(self, _ctx: object) -> list[str]:
        return []
