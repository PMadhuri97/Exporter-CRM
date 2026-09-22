"""Indicative rate providers for tests.

Test doubles rather than a Crawl-phase implementation, which is why they live
here and not in ``infrastructure/``: nothing wires a rate provider into the
application yet, and shipping a stub that returns invented rates in production
code is how an invented rate later ends up deciding a real review.

Each satisfies ``IndicativeRateProvider`` structurally, without importing it —
which is the point of a Protocol, and what keeps compliance from depending on
any particular implementation.
"""

from __future__ import annotations

from decimal import Decimal


class StubIndicativeRateProvider:
    """Returns rates from a table, and records what it was asked.

    ``calls`` exists so a test can assert that no lookup happened at all — the
    same-currency case is meant to skip the provider entirely, and a provider
    that was consulted and happened to return 1 would pass every assertion about
    the resulting amount while failing the thing being tested.
    """

    def __init__(self, rates: dict[tuple[str, str], Decimal]) -> None:
        self.rates = rates
        self.calls: list[tuple[str, str]] = []

    async def get_indicative_rate(self, from_asset_code: str, to_asset_code: str) -> Decimal:
        self.calls.append((from_asset_code, to_asset_code))
        try:
            return self.rates[(from_asset_code, to_asset_code)]
        except KeyError:
            raise LookupError(
                f"no indicative rate for {from_asset_code}->{to_asset_code}"
            ) from None


class UnavailableRateProvider:
    """Fails every lookup, the way an unreachable rate feed does."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or ConnectionError("indicative rate feed is unreachable")
        self.calls: list[tuple[str, str]] = []

    async def get_indicative_rate(self, from_asset_code: str, to_asset_code: str) -> Decimal:
        self.calls.append((from_asset_code, to_asset_code))
        raise self.error


class FloatRateProvider:
    """Returns a float, which no rate may be.

    Present so the rejection is provable end to end rather than only at the
    conversion helper: a provider written against a JSON feed is exactly where
    a float would enter.
    """

    def __init__(self, rate: float) -> None:
        self.rate = rate

    async def get_indicative_rate(self, from_asset_code: str, to_asset_code: str) -> float:
        return self.rate
