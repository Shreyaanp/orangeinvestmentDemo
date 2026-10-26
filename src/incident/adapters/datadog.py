"""Datadog: logs (Logs Search v2) and metrics (Metrics Query v1) mapped to our typed models."""

from datetime import UTC, datetime
from urllib.parse import quote

from incident.adapters.ports import Http
from incident.models import Level, LogLine, Series
from incident.redact import redact

LEVELS: dict[str, Level] = {
    "emergency": "ERROR",
    "alert": "ERROR",
    "critical": "ERROR",
    "error": "ERROR",
    "warn": "WARN",
    "warning": "WARN",
    "notice": "INFO",
    "info": "INFO",
    "debug": "DEBUG",
}
# Example queries; override to match how the team tags its services.
DEFAULT_METRICS = {
    "rps": "sum:trace.http.request.hits{{service:{svc}}}.as_count()",
    "latency_ms": "avg:trace.http.request.duration.by.service.95p{{service:{svc}}}",
    "err_rate": "sum:trace.http.request.errors{{service:{svc}}}.as_count()",
}


class Datadog:
    def __init__(
        self,
        http: Http,
        api_key: str,
        app_key: str,
        site: str = "datadoghq.com",
        page_size: int = 500,
        max_pages: int = 5,
        metric_queries: dict[str, str] | None = None,
    ) -> None:
        self.http, self.site, self.page_size, self.max_pages = http, site, page_size, max_pages
        self.queries = metric_queries or DEFAULT_METRICS
        self.headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}

    def _link(self, query: str, start: datetime, end: datetime) -> str:
        lo, hi = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        return f"https://app.{self.site}/logs?query={quote(query)}&from_ts={lo}&to_ts={hi}"

    async def logs(self, services: list[str], start: datetime, end: datetime) -> list[LogLine]:
        query = " OR ".join(f"service:{s}" for s in services) or "*"
        body = {
            "filter": {"query": query, "from": start.isoformat(), "to": end.isoformat()},
            "sort": "timestamp",
            "page": {"limit": self.page_size},
        }
        url, link, out = (
            f"https://api.{self.site}/api/v2/logs/events/search",
            self._link(query, start, end),
            [],
        )
        for _ in range(self.max_pages):
            resp = await self.http.request("POST", url, headers=self.headers, json=body)
            out += [self._line(e, link) for e in resp.get("data", [])]
            cursor = (resp.get("meta") or {}).get("page", {}).get("after")
            if not cursor:
                return out
            body["page"] = {"limit": self.page_size, "cursor": cursor}
        return out  # capped: the caller records that the window may be incomplete

    @staticmethod
    def _line(event: dict, link: str) -> LogLine:  # type: ignore[type-arg]
        a = event.get("attributes", {})
        return LogLine(
            ts=datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")),
            service=a.get("service", "unknown"),
            host=a.get("host", "unknown"),
            level=LEVELS.get(str(a.get("status", "info")).lower(), "INFO"),
            msg=redact(str(a.get("message", ""))),
            source="datadog",
            url=link,
        )

    async def metrics(self, services: list[str], start: datetime, end: datetime) -> Series:
        minutes = int((end - start).total_seconds() // 60)
        out: Series = {}
        for svc in services:
            out[svc] = {}
            for name, template in self.queries.items():
                params = {
                    "from": int(start.timestamp()),
                    "to": int(end.timestamp()),
                    "query": template.format(svc=svc),
                }
                resp = await self.http.request(
                    "GET",
                    f"https://api.{self.site}/api/v1/query",
                    headers=self.headers,
                    params=params,
                )
                values = bucket(resp.get("series", []), start, minutes)
                if any(
                    v is not None for v in values
                ):  # no series at all means the metric is absent
                    out[svc][name] = values
        return out


def bucket(series: list[dict], start: datetime, minutes: int) -> list[float | None]:  # type: ignore[type-arg]
    """Resample Datadog's [[ms, value], ...] points onto per-minute slots; gaps stay None."""
    sums, counts = [0.0] * minutes, [0] * minutes
    for s in series:
        for ts_ms, value in s.get("pointlist", []):
            i = int((ts_ms / 1000 - start.astimezone(UTC).timestamp()) // 60)
            if value is not None and 0 <= i < minutes:
                sums[i] += value
                counts[i] += 1
    return [round(sums[i] / counts[i], 3) if counts[i] else None for i in range(minutes)]
