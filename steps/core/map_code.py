"""map.code — point at an existing source graft/ index. Never run graft."""

from __future__ import annotations

from extractkit_cli.readiness import GRAFT_FIX


class MapCodeStep:
    id = "map.code"
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    required = False

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        source = ctx.source  # type: ignore[attr-defined]
        graft = source / "graft"
        if graft.is_dir():
            ctx.map_pointers["code"] = str(graft)  # type: ignore[attr-defined]
            ctx.plan.record(f"reuse code map {graft}")  # type: ignore[attr-defined]
            return
        ctx.map_pointers["code"] = None  # type: ignore[attr-defined]
        ctx.record_skip(  # type: ignore[attr-defined]
            self.id,
            f"no graft/ index in {source}",
            GRAFT_FIX.format(source=source),
        )

    def check(self, _ctx: object) -> list[str]:
        return []
