"""Exact settlement calculations. Activation policy belongs to the caller."""

from dataclasses import dataclass
from decimal import Decimal

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Settlement:
    hours: int
    hourly_amount: Decimal
    separate_amount: Decimal
    adjustment: Decimal
    debt: Decimal


def _cents(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("Expected a nonnegative Decimal amount")
    numerator, denominator = value.as_integer_ratio()
    cents, rest = divmod(numerator * 100, denominator)
    if rest:
        raise ValueError("Expected an exact number of kopecks")
    return cents


def align_payment(debt: Decimal, requested: Decimal, rate: Decimal, mode: str,
                  *, adjustment_authorized: bool = False, separate_channel: bool = False) -> Settlement:
    owed, budget, wage = map(_cents, (debt, requested, rate))
    if not wage or budget > owed:
        raise ValueError("Invalid rate or requested amount")
    hours, remainder = divmod(budget, wage)
    adjustment = separate = 0
    if mode == "up":
        if remainder:
            if not adjustment_authorized:
                raise ValueError("Rounding up requires an approved adjustment")
            hours += 1
            adjustment = wage - remainder
    elif mode == "separate":
        if remainder and not separate_channel:
            raise ValueError("A separate channel is required")
        separate = remainder
    elif mode != "down":
        raise ValueError("Unknown settlement mode")
    paid = hours * wage

    def rubles(cents: int) -> Decimal:
        return Decimal((0, tuple(map(int, str(cents))), -2))

    return Settlement(hours, rubles(paid), rubles(separate), rubles(adjustment),
                      rubles(owed + adjustment - paid - separate))
