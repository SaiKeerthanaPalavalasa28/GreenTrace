"""Consumption quantity of a bill: the printed total, or (current - previous) x multiplier
when only meter readings are printed. The LLM never does this arithmetic."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class QuantityResult:
    value: Decimal | None
    source: str  # "printed" | "meter_readings" | "missing"
    formula: str
    issues: list[tuple[str, str]] = field(default_factory=list)  # (code, message)


def effective_quantity(
    quantity: Decimal | None,
    previous: Decimal | None,
    current: Decimal | None,
    multiplier: Decimal | None,
) -> QuantityResult:
    has_readings = previous is not None and current is not None

    if quantity is not None:
        result = QuantityResult(quantity, "printed", f"{quantity} (printed on bill)")
        if has_readings:
            derived = (current - previous) * (multiplier if multiplier is not None else Decimal(1))
            if derived != quantity:
                result.issues.append((
                    "meter_mismatch",
                    f"Printed consumption {quantity} does not match meter readings "
                    f"({current} - {previous}) x {multiplier if multiplier is not None else 1} = {derived}",
                ))
        return result

    if not has_readings:
        return QuantityResult(None, "missing", "", [("quantity_missing", "No consumption figure or meter readings found")])

    diff = current - previous
    if diff < 0:
        return QuantityResult(None, "missing", "", [(
            "meter_rollover",
            f"Current reading {current} is lower than previous {previous} (meter rollover or replacement?)",
        )])
    result = QuantityResult(None, "meter_readings", "")
    if multiplier is None:
        result.issues.append((
            "multiplier_not_printed",
            "No meter multiplier printed; assumed 1. Check the bill: CT-metered supplies often use a multiplier.",
        ))
        multiplier = Decimal(1)
    result.value = diff * multiplier
    result.formula = f"({current} - {previous}) x {multiplier} = {result.value}"
    return result
