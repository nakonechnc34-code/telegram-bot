"""Round daily attendance once, preserving restaurant allocation totals."""
from decimal import Decimal, ROUND_HALF_UP


def round_daily_minutes(minutes, step=5):
    if step not in (1, 5, 10, 15, 30, 60):
        raise ValueError("invalid rounding step")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 1440:
        raise ValueError("invalid daily minutes")
    return int((Decimal(minutes) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * step


def allocate_daily_minutes(by_restaurant, step=5):
    """Allocate rounded daily total proportionally using largest remainders."""
    for minutes in by_restaurant.values():
        round_daily_minutes(minutes, 1)
    total = sum(by_restaurant.values())
    rounded = round_daily_minutes(total, step)
    if not total:
        return dict(by_restaurant)
    result = {key: minutes * rounded // total for key, minutes in by_restaurant.items()}
    order = sorted(by_restaurant, key=lambda key: (-(by_restaurant[key] * rounded % total), key))
    for key in order[:rounded - sum(result.values())]:
        result[key] += 1
    return result
