"""Async circuit breaker for transient PayPal API failures."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from time import monotonic

from app.integrations.paypal.errors import PayPalCircuitOpenError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Reject calls during an outage and allow one probe after the cooldown."""

    def __init__(self, *, failure_threshold: int, reset_timeout: float) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if reset_timeout <= 0:
            raise ValueError("reset_timeout must be positive")
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failure_count = 0
        self._opened_at: float | None = None
        self._state = CircuitState.CLOSED
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def before_call(self) -> None:
        """Raise while open; serialize half-open probes."""
        async with self._lock:
            now = monotonic()
            if self._state is CircuitState.OPEN:
                opened_at = self._opened_at
                if opened_at is None:
                    raise RuntimeError("Open circuit is missing its opening time")
                remaining = self._reset_timeout - (now - opened_at)
                if remaining > 0:
                    raise PayPalCircuitOpenError(retry_after_seconds=remaining)
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = False

            if self._state is CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    raise PayPalCircuitOpenError(
                        retry_after_seconds=self._reset_timeout
                    )
                self._probe_in_flight = True

    async def record_success(self) -> None:
        """Close the circuit and clear consecutive failures."""
        async with self._lock:
            self._failure_count = 0
            self._opened_at = None
            self._probe_in_flight = False
            self._state = CircuitState.CLOSED

    async def record_failure(self) -> None:
        """Count a transient failure and open the circuit at the threshold."""
        async with self._lock:
            self._failure_count += 1
            if (
                self._state is CircuitState.HALF_OPEN
                or self._failure_count >= self._failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = monotonic()
                self._probe_in_flight = False
