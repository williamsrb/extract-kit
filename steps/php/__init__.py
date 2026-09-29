"""PHP v1 adapter: deliberately unfinished. A guessed parser is worse."""

from __future__ import annotations

from extractkit_cli import manifest


def _todo_text(ctx: object) -> str:
    profile = getattr(ctx, "profile", {}) or {}
    items = manifest.unfinished_work(profile)
    if not items:
        items = [
            "PHP adapters are not implemented.",
            "Bind inventory.descriptors and inventory.integrations when the stack is known.",
        ]
    return "PHP profile is unfinished:\n" + "\n".join(f"  - {item}" for item in items)


class PhpPlaceholderStep:
    id = "php.placeholder"
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    required = True

    def plan(self, ctx: object) -> list[str]:
        raise NotImplementedError(_todo_text(ctx))

    def run(self, ctx: object) -> None:
        raise NotImplementedError(_todo_text(ctx))

    def check(self, ctx: object) -> list[str]:
        raise NotImplementedError(_todo_text(ctx))
