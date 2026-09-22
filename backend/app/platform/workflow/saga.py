from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@dataclass
class _CompensationEntry:
    activity: Any
    arg: Any


class Saga:

    def __init__(self) -> None:
        self._compensations: list[_CompensationEntry] = []

    def add_compensation(self, activity: Any, arg: Any) -> None:
        self._compensations.append(_CompensationEntry(activity=activity, arg=arg))

    async def compensate(
        self,
        *,
        timeout: timedelta = timedelta(seconds=60),
    ) -> bool:
        _compensation_retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_attempts=100,
        )

        success = True
        for entry in reversed(self._compensations):
            try:
                await workflow.execute_activity(
                    entry.activity,
                    entry.arg,
                    start_to_close_timeout=timeout,
                    retry_policy=_compensation_retry,
                )
            except Exception as exc:  # noqa: BLE001
                success = False
                workflow.logger.error(
                    "saga_compensation_failed",
                    extra={
                        "activity": getattr(entry.activity, "__name__", str(entry.activity)),
                        "error": str(exc),
                    },
                )
        return success
