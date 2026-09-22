from datetime import date


def is_effective_at(effective_from: date, effective_to: date | None, on: date) -> bool:
    """
    Check if an effective-dated registry row is in force on a given date.
    Implements half-open date logic: [effective_from, effective_to)
    If effective_to is None, it is effective indefinitely.
    """
    if on < effective_from:
        return False
    if effective_to is not None and on >= effective_to:
        return False
    return True
