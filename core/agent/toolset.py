"""The built-in data tools, registered by discovery. The one place that names them.

Each known tool module is imported when it exists; a tool whose module (or function, or argument
model) is not there yet is skipped with one debug line, so tools arrive in the pipeline as their
branches merge, without the pipeline depending on them. To add a tool, add a row to KNOWN_TOOLS.
Every tool follows tool(ctx, args) -> ToolResult with an argument model, a card and a model_view.
The pipeline (orchestrator.py) never names a tool; it reads them from the registry built here.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass

from core.agent.registry import Registry, ToolSpec

log = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class KnownTool:
    module: str
    function: str
    args_model: str
    description: str
    status_label: tuple[str, str]


KNOWN_TOOLS = [
    KnownTool("core.tools.spending", "get_spending", "GetSpendingArgs",
              "Total spending or income of the current user for a period, optionally filtered, grouped and compared "
              "with an earlier period. Returns numbers with ids; cite them as {{id}}.",
              ("Looking at your spending", "Katson kulutustasi")),
    KnownTool("core.tools.baskets", "get_basket_breakdown", "GetBasketBreakdownArgs",
              "Split of spending into the three baskets (regular essentials, unexpected necessities, everyday "
              "spending) for a period. Returns numbers with ids; cite them as {{id}}.",
              ("Sorting your spending into baskets", "Jaan kulutuksesi koreihin")),
    KnownTool("core.tools.bills", "get_recurring_bills", "GetRecurringBillsArgs",
              "Recurring bills and income: typical monthly amounts, what is paid this month and what is due "
              "before payday. Returns numbers with ids; cite them as {{id}}.",
              ("Checking your regular bills", "Tarkistan säännölliset laskusi")),
    KnownTool("core.tools.safe_to_spend", "get_safe_to_spend", "GetSafeToSpendArgs",
              "What the user can safely spend in the next 7 days, with its components. An estimate. Returns "
              "numbers with ids; cite them as {{id}}.",
              ("Working out what is safe to spend", "Lasken, paljonko on turvallisesti käytettävissä")),
    KnownTool("core.tools.safe_to_save", "get_safe_to_save", "GetSafeToSaveArgs",
              "What a typical month leaves for saving and the money beyond what is needed until payday, with "
              "their components and, when a month leaves nothing, the main reason. An estimate. Returns "
              "numbers with ids; cite them as {{id}}.",
              ("Working out what you could save", "Lasken, paljonko voit säästää")),
    KnownTool("core.tools.bonus", "get_bonus_estimate", "GetBonusEstimateArgs",
              "The S-Bonus and payment benefit a month and a year for a share of the user's grocery spending "
              "(the share only if the user gave one, else the default), with fixed assumptions. An estimate; "
              "never says where the user shops. Returns numbers with ids; cite them as {{id}}.",
              ("Estimating your S-Bonus", "Arvioin S-Bonuksesi")),
    KnownTool("core.tools.forecast", "get_balance_forecast", "GetBalanceForecastArgs",
              "The balance from today to the day before payday if the user spends as usual: the lowest projected "
              "balance and its date, whether it goes below zero, the bills before payday and the usual spending a "
              "day. An estimate. Returns numbers with ids; cite them as {{id}}.",
              ("Projecting your balance until payday", "Ennustan saldosi palkkapäivään asti")),
    KnownTool("core.tools.what_if", "run_what_if", "ModelWhatIfArgs",   # group names accepted (#346)
              "Savings from cutting a selection by a percentage, from the last 6 complete months. The selection "
              "is a spending category, a basket, a merchant-category group (kind mcc, value taxi, "
              "public_transport, fuel, parking, restaurants, groceries or electronics_home) or a merchant alias. "
              "An estimate. Returns numbers with ids; cite them as {{id}}.",
              ("Calculating the saving", "Lasken säästön")),
    # Issue #69: the spender profile and the peer benchmark (core/tools/profile.py, core/tools/peer.py).
    KnownTool("core.tools.profile", "get_spender_profile", "GetSpenderProfileArgs",
              "What kind of spender the user is: a profile key, traits and the features that decided them.",
              ("Looking at your spending habits", "Katson kulutustottumuksiasi")),
    KnownTool("core.tools.peer", "get_peer_benchmark", "GetPeerBenchmarkArgs",
              "Comparison with people of the same age band and area: median, quartiles and percentile.",
              ("Comparing with people like you", "Vertaan kaltaisiisi")),
    # Issue #256: small everyday purchases (core/tools/small_purchases.py).
    KnownTool("core.tools.small_purchases", "get_small_purchases", "GetSmallPurchasesArgs",
              "Small everyday purchases (restaurants, entertainment, lifestyle) of at most max_amount euros in a "
              "period, by default the last 3 complete months and 10 euros: count, total, average, a month, share "
              "of everyday spending and the total per category. Pass max_amount or a period only if the user named "
              "them. Returns numbers with ids; cite them as {{id}}.",
              ("Adding up your small purchases", "Lasken pienet ostoksesi yhteen")),
]


def builtin_tools() -> Iterator[ToolSpec]:
    for known in KNOWN_TOOLS:
        try:
            module = importlib.import_module(known.module)
            fn = getattr(module, known.function)
            args_model = getattr(module, known.args_model)
        except (ImportError, AttributeError):
            log.debug("tool %s is not available yet; not registered", known.function)
            continue
        yield ToolSpec(name=known.function, description=known.description, args_model=args_model, fn=fn,
                       status_label=known.status_label)


def default_registry() -> Registry:
    registry = Registry()
    for spec in builtin_tools():
        registry.register(spec)
    return registry
