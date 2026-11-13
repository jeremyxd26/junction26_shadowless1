"""The built-in data tools. The one place that names them: add a ToolSpec here to register a tool.

The pipeline (orchestrator.py) never names a tool; it reads them from the registry built here.
"""

from __future__ import annotations

from core.agent.registry import Registry, ToolSpec


def builtin_tools() -> list[ToolSpec]:
    from core.tools.spending import TOOL as SPENDING, GetSpendingArgs, get_spending

    return [
        ToolSpec(
            name=SPENDING,
            description=("Total spending or income of the current user for a period, optionally filtered, "
                         "grouped and compared with an earlier period. Returns numbers with ids; cite them as {{id}}."),
            args_model=GetSpendingArgs,
            fn=get_spending,
            status_label=("Looking at your spending", "Katson kulutustasi"),
        ),
    ]


def default_registry() -> Registry:
    registry = Registry()
    for spec in builtin_tools():
        registry.register(spec)
    return registry
