"""Ports: what the investigator needs from any infrastructure, plus the shared HTTP layer."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar, Protocol

import httpx

from incident.models import Change, LogLine, Series
from incident.redact import redact
from incident.tools.schemas import ToolError, ToolTimeout, ToolUnavailable

RETRYABLE = {429, 500, 502, 503, 504}


class AuthError(ToolError):
    kind: ClassVar[Any] = "error"


class LogFetcher(Protocol):
    async def logs(self, services: list[str], start: datetime, end: datetime) -> list[LogLine]: ...


class MetricFetcher(Protocol):
    async def metrics(self, services: list[str], start: datetime, end: datetime) -> Series: ...


class ChangeFetcher(Protocol):
    async def changes(self, start: datetime, end: datetime) -> list[Change]: ...


class Http:
    """Thin async client: bounded retries with backoff and the tool layer's typed errors."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        retries: int = 2,
        backoff_s: float = 0.5,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.client = client or httpx.AsyncClient(timeout=15.0)
        self.retries, self.backoff_s, self.sleep = retries, backoff_s, sleep

    async def request(self, method: str, url: str, **kw: Any) -> Any:
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            try:
                r = await self.client.request(method, url, **kw)
            except httpx.TimeoutException as e:
                if last:
                    raise ToolTimeout(f"{url} timed out") from e
            except httpx.TransportError as e:
                raise ToolUnavailable(f"{url} unreachable: {e}") from e
            else:
                if r.status_code in RETRYABLE and last:
                    raise ToolUnavailable(f"{url} returned HTTP {r.status_code}")
                if r.status_code not in RETRYABLE:
                    return self._body(r, url)
            await self.sleep(self.backoff_s * 2**attempt)
        raise AssertionError("unreachable")

    @staticmethod
    def _body(r: httpx.Response, url: str) -> Any:
        if r.status_code in (401, 403):
            raise AuthError(f"{url}: authentication or permission failure (HTTP {r.status_code})")
        if r.status_code >= 400:
            raise ToolError(f"{url}: HTTP {r.status_code} {redact(r.text[:200])}")
        return r.json()
