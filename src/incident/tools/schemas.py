"""Shared tool primitives: UTC datetimes, typed errors, the generic result envelope."""

from datetime import UTC, datetime
from typing import Annotated, ClassVar, Literal

from pydantic import AfterValidator

from incident.models import Strict

ErrorKind = Literal["timeout", "unavailable", "invalid_input", "error"]


def _utc(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]


class ToolError(Exception):
    kind: ClassVar[ErrorKind] = "error"
    retryable: ClassVar[bool] = False


class ToolTimeout(ToolError):
    kind: ClassVar[ErrorKind] = "timeout"
    retryable: ClassVar[bool] = True


class ToolUnavailable(ToolError):
    kind: ClassVar[ErrorKind] = "unavailable"
    retryable: ClassVar[bool] = True


class InvalidInput(ToolError):
    kind: ClassVar[ErrorKind] = "invalid_input"


class Result[T](Strict):
    """items plus honesty flags. total is None when the source could not say (partial)."""

    items: list[T]
    total: int | None
    truncated: bool = False
    partial: bool = False
    note: str | None = None
