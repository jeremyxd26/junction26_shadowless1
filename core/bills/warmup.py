"""Read the gallery's sample bills at deploy (#250), inside the running service container.

Each sample is read twice with the service's own model client, budget and cache: the first reading costs
one model request unless the cache already holds it, the second must come from the cache (no request).
The first reading is compared with the answer key. Only counts are printed, never a field value, and the
image is never written anywhere. It never fails the deploy: every problem is one printed line, exit 0.

    python -m core.bills.warmup        # in the service container (deploy/remote-deploy.sh): the Gemini reader
    python -m core.bills.warmup --reader nemotron   # Nemotron first (#573): only by hand, on the coordinator's word
    python -m core.bills.warmup --reader nemotron-only   # Nemotron alone (#637): a timeout shows as a timeout

Without one of those switches the warm-up never calls the Nemotron provider, whatever the environment holds (#594,
D1). With `nemotron` a Nemotron timeout is followed by a Gemini reading (one Gemini request); `nemotron-only`
never builds the Gemini reader, so it warms the Nemotron cache and nothing else.

The same run with a key on a developer machine is the accuracy check of #250 (four requests the first
time; ask the coordinator before any further real run).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from core.bills import gallery
from core.bills.read import BillReadUnavailable, read_bill

FIELDS = ("payee", "iban", "reference", "amount", "due_date", "barcode")


def _norm(name: str, value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if name in ("iban", "reference", "barcode"):
        return "".join(text.split()).upper()
    if name == "amount":
        try:
            return str(Decimal(text.replace(" ", "").replace(",", ".")).quantize(Decimal("0.01")))
        except InvalidOperation:
            return text
    return " ".join(text.split()).casefold()


def score(fields: dict[str, Any], truth: dict[str, Any]) -> tuple[int, int, int]:
    """(correct, total, checked by code) for one reading. A field is correct when its value matches the
    answer key, or when the key has none and nothing was read (the barcode of a bill without one)."""
    correct = checked = 0
    for name in FIELDS:
        got = fields.get(name) or None
        if _norm(name, got["value"] if got else None) == _norm(name, truth.get(name)):
            correct += 1
        if got and got.get("status") == "checked":
            checked += 1
    return correct, len(FIELDS), checked


def reading_client(nemotron: bool = False, alone: bool = False) -> Any | None:
    """The reader the service builds (the same keys, budgets, ledgers and cache): the Gemini client, or None
    without a key. With `nemotron` (the command line's --reader nemotron, #594 D1) Nemotron with the Gemini extract
    role as its fallback when Nemotron is set up (#573). With `alone` (--reader nemotron-only, #637) the Nemotron
    client alone, or None when Nemotron is not set up."""
    if alone:
        from pathlib import Path

        from core.agent.gemini import OFF_SWITCH, GeminiSettings
        from core.bills.nemotron import NemotronSettings, make_nemotron_client
        env = GeminiSettings()
        return make_nemotron_client(NemotronSettings(), cache=env.gemini_cache, cache_dir=Path(env.gemini_cache_dir),
                                    off_switch=OFF_SWITCH)
    from core.agent.gemini import make_agent_model
    from core.app.settings import Settings

    model = make_agent_model(Settings())
    gemini = getattr(model, "client", None) or getattr(getattr(model, "model", None), "client", None)
    if not nemotron:
        return gemini
    from core.bills.nemotron import make_reader
    return make_reader(gemini)


def run(client: Any, out: Callable[[str], None] = print) -> tuple[int, int]:
    """Read every sample twice; print one line per sample. Returns (fields correct, fields total)."""
    ledger = getattr(client, "ledger", None)

    def sent() -> int:
        return ledger.count("extract") if ledger is not None else 0

    try:
        truth = {s["sample_id"]: s["truth"] for s in gallery.answer_key()["samples"]}
        samples = gallery.gallery()
    except Exception as exc:  # noqa: BLE001 - a deploy never fails here (review of #250)
        out(f"bill readings skipped: the sample gallery could not be read ({type(exc).__name__})")
        return 0, 0
    correct = total = 0
    for sample in samples:
        try:
            image = sample.png.read_bytes()
        except Exception as exc:  # noqa: BLE001
            out(f"bill reading {sample.sample_id}: its image could not be read ({type(exc).__name__})")
            continue
        parts = []
        for attempt in ("first", "second"):
            before = sent()
            try:
                # The second reading only reads the cache (#511): with an unwritable cache folder a sample
                # costs one request, not two.
                result = read_bill(client, image, "image/png", "en", cache_only=attempt == "second")
            except BillReadUnavailable as exc:
                if exc.reason == "cache_miss":
                    parts.append(f"{attempt} reading: not in the cache (the cache folder may not be writable)")
                else:
                    parts.append(f"{attempt} reading: model unavailable ({exc.reason})")
                break
            except Exception as exc:  # noqa: BLE001 - the class name only; a deploy never fails here
                parts.append(f"{attempt} reading failed ({type(exc).__name__})")
                break
            requests = sent() - before
            if attempt == "first":
                c, n, checked = score(result["fields"], truth.get(sample.sample_id, {}))
                correct, total = correct + c, total + n
                parts.append(f"{c}/{n} fields match the answer key, {checked} checked by code; "
                             f"first reading {requests} request(s)")
            else:
                parts.append(f"second reading {requests} request(s)" + (" (cache)" if requests == 0 else ""))
        out(f"bill reading {sample.sample_id}: " + "; ".join(parts))
    if total:
        out(f"bill readings: {correct}/{total} fields match the answer key")
    return correct, total


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    nemotron = args in (["--reader", "nemotron"], ["--reader=nemotron"])
    alone = args in (["--reader", "nemotron-only"], ["--reader=nemotron-only"])
    try:
        client = (reading_client(alone=True) if alone else reading_client(nemotron=True) if nemotron
                  else reading_client())
    except Exception as exc:  # noqa: BLE001
        print(f"bill readings skipped: the model could not be set up ({type(exc).__name__})")
        return 0
    if client is None:
        print("bill readings skipped: " + ("Nemotron is not set up" if alone else "no model key"))
        return 0
    try:
        run(client)
    except Exception as exc:  # noqa: BLE001 - counts or a class name, never a failed deploy (review of #250)
        print(f"bill readings stopped ({type(exc).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
