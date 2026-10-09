"""Step plugin registry.

Unknown adapter ids fail profile load with a named fix. PHP plugins exist so
the package is importable; running them raises NotImplementedError.
"""

from __future__ import annotations

from typing import Protocol

from .errors import ExtractkitError


class Step(Protocol):
    id: str
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    required: bool

    def plan(self, ctx: object) -> list[str]: ...
    def run(self, ctx: object) -> None: ...
    def check(self, ctx: object) -> list[str]: ...


def _load() -> dict[str, type]:
    # Imported lazily so `extractkit profile` works before every adapter module
    # is imported in tests that only exercise composition.
    from steps.core.impeccable import ImpeccableStep
    from steps.core.map_code import MapCodeStep
    from steps.core.map_semantic import MapSemanticStep
    from steps.core.merge import MergeStep
    from steps.core.normalize import NormalizeStep
    from steps.core.speckit import SpeckitStep
    from steps.core.synthesize import SynthesizeStep
    from steps.core.templates import TemplatesStep
    from steps.core.use_cases import UseCasesStep
    from steps.core.view_rules import ViewRulesStep
    from steps.enonic.baseline import EnonicBaselineStep
    from steps.enonic.cms import EnonicCmsStep
    from steps.enonic.compat import EnonicCompatStep
    from steps.enonic.controllers import EnonicControllersStep
    from steps.enonic.descriptors import EnonicDescriptorsStep
    from steps.enonic.docs import EnonicDocsStep
    from steps.enonic.domain_packet import EnonicDomainPacketStep
    from steps.enonic.integrations import EnonicIntegrationsStep
    from steps.php import PhpPlaceholderStep

    plugins = [
        MapCodeStep,
        MapSemanticStep,
        NormalizeStep,
        TemplatesStep,
        ViewRulesStep,
        MergeStep,
        EnonicDescriptorsStep,
        EnonicControllersStep,
        EnonicIntegrationsStep,
        EnonicCmsStep,
        EnonicBaselineStep,
        EnonicCompatStep,
        EnonicDocsStep,
        EnonicDomainPacketStep,
        ImpeccableStep,
        SynthesizeStep,
        UseCasesStep,
        SpeckitStep,
        PhpPlaceholderStep,
    ]
    return {cls.id: cls for cls in plugins}


_CACHE: dict[str, type] | None = None


def all_steps() -> dict[str, type]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load()
    return _CACHE


def get(step_id: str) -> type:
    plugins = all_steps()
    if step_id not in plugins:
        known = ", ".join(sorted(plugins)) or "none"
        raise ExtractkitError(
            f"unknown step id {step_id!r}",
            f"registered plugins: {known}",
        )
    return plugins[step_id]


def instantiate(step_id: str) -> Step:
    return get(step_id)()
