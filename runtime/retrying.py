"""Shared retry/backoff helpers for Video Director network operations."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Tuple, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Finite retry/backoff configuration."""

    max_attempts: int = 1
    initial_backoff_seconds: float = 0.75
    max_backoff_seconds: float = 8.0
    backoff_multiplier: float = 2.0
    jitter_seconds: float = 0.15
    retryable_http_statuses: Tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)

    @classmethod
    def from_config(cls, raw: Any) -> "RetryPolicy":
        cfg = raw if isinstance(raw, dict) else {}
        statuses = cfg.get("retryable_http_statuses", cls.retryable_http_statuses)
        values = tuple(int(item) for item in statuses) if isinstance(statuses, (list, tuple, set)) else cls.retryable_http_statuses
        return cls(
            max_attempts=max(int(cfg.get("max_attempts", cls.max_attempts)), 1),
            initial_backoff_seconds=max(float(cfg.get("initial_backoff_seconds", cls.initial_backoff_seconds)), 0.0),
            max_backoff_seconds=max(float(cfg.get("max_backoff_seconds", cls.max_backoff_seconds)), 0.0),
            backoff_multiplier=max(float(cfg.get("backoff_multiplier", cls.backoff_multiplier)), 1.0),
            jitter_seconds=max(float(cfg.get("jitter_seconds", cls.jitter_seconds)), 0.0),
            retryable_http_statuses=values,
        )


class RetryExhaustedError(RuntimeError):
    """Raised when retryable work still fails after the configured attempts."""

    def __init__(self, label: str, attempts: int, last_error: Exception):
        super().__init__(f"{label} failed after {attempts} attempts: {last_error}")
        self.label = label
        self.attempts = attempts
        self.last_error = last_error


def call_with_retry(
    fn: Callable[[int], T],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool],
    label: str,
    logger: Optional[Callable[[str], None]] = None,
) -> T:
    """Run `fn` with finite exponential backoff."""

    last_error: Optional[Exception] = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn(attempt)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= policy.max_attempts or not should_retry(exc):
                raise RetryExhaustedError(label, attempt, exc) from exc
            if logger is not None:
                logger(f"{label} retry attempt={attempt + 1}/{policy.max_attempts} reason={exc}")
            time.sleep(_compute_backoff(policy, attempt))

    assert last_error is not None
    raise RetryExhaustedError(label, policy.max_attempts, last_error)


def _compute_backoff(policy: RetryPolicy, attempt: int) -> float:
    backoff = policy.initial_backoff_seconds * (policy.backoff_multiplier ** max(attempt - 1, 0))
    backoff = min(backoff, policy.max_backoff_seconds)
    if policy.jitter_seconds > 0:
        backoff += random.uniform(0.0, policy.jitter_seconds)
    return max(backoff, 0.0)

