"""Local stand-ins for Datadog, GitHub, GCP Cloud Audit Logs and CloudFormation.

They speak the real wire formats (paths, headers, request and response shapes, pagination
cursors, status codes) but serve a scenario's Dataset, so the adapters can be proved correct
end to end without credentials or network. Optional fault injection exercises retry paths.
"""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from incident.models import Change, Dataset

STATUS = {"ERROR": "error", "WARN": "warn", "INFO": "info", "DEBUG": "debug"}
GCP_METHOD = {
    "config": "google.cloud.secretmanager.v1.SecretManagerService.AddSecretVersion",
    "migration": "google.cloud.sql.v1.SqlInstancesService.Update",
    "flag": "google.cloud.runtimeconfig.v1beta1.RuntimeConfigManager.UpdateVariable",
}
DD_KEY, GCP_TOKEN, GH_TOKEN = "mock-dd-key", "mock-gcp-token", "mock-gh-token"


class Faults(BaseModel):
    rate_limit_every: int = 0  # every Nth request gets HTTP 429
    fail_prefix: str | None = None  # requests under this path always get HTTP 503


def sha(ref: str) -> str:
    return hashlib.sha1(ref.encode(), usedforsecurity=False).hexdigest()  # git ids are sha1


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def deploys(data: Dataset, service: str) -> list[Change]:
    return [c for c in data.changes if c.kind == "deploy" and c.service == service]


class FakeCloudFormation:
    """Quacks like a boto3 CloudFormation client: config-like changes become stack events."""

    def __init__(self, data: Dataset) -> None:
        self.data = data

    def describe_stack_events(self, StackName: str) -> dict[str, Any]:  # noqa: N803
        events = [
            {
                "StackId": f"arn:aws:cloudformation:us-east-1:123456789012:stack/{c.service}/1",
                "EventId": c.ref,
                "StackName": c.service,
                "LogicalResourceId": f"{c.service}Config",
                "ResourceType": "AWS::CloudFormation::Stack",
                "ResourceStatus": "UPDATE_COMPLETE",
                "ResourceStatusReason": c.note,
                "Timestamp": c.ts,
            }
            for c in self.data.changes
            if c.kind != "deploy" and c.service == StackName
        ]
        return {"StackEvents": events}


def _faults(app: FastAPI, faults: Faults) -> None:
    seen = [0]
    app.state.calls = []  # (method, path, status): the wire traffic, for demos and assertions

    @app.middleware("http")
    async def inject(request: Request, call_next):  # type: ignore[no-untyped-def]
        seen[0] += 1
        path = request.url.path
        if faults.fail_prefix and path.startswith(faults.fail_prefix):
            response = JSONResponse({"error": "service unavailable"}, status_code=503)
        elif faults.rate_limit_every and seen[0] % faults.rate_limit_every == 0:
            response = JSONResponse(
                {"error": "rate limited"}, status_code=429, headers={"Retry-After": "0"}
            )
        else:
            response = await call_next(request)
        app.state.calls.append(
            (request.method, re.sub(r"/commits/\w+", "/commits/{sha}", path), response.status_code)
        )
        return response


def _datadog(app: FastAPI, data: Dataset) -> None:
    def need_dd(api: str | None, app_key: str | None) -> None:
        if api != DD_KEY or not app_key:
            raise HTTPException(403, "Forbidden")

    @app.post("/api/v2/logs/events/search")
    async def dd_logs(
        body: dict[str, Any],
        api: str | None = Header(default=None, alias="DD-API-KEY"),
        app_key: str | None = Header(default=None, alias="DD-APPLICATION-KEY"),
    ) -> dict[str, Any]:
        need_dd(api, app_key)
        flt, page = body.get("filter", {}), body.get("page", {})
        services = set(re.findall(r"service:([\w-]+)", flt.get("query", "")))
        lo, hi = parse_time(flt["from"]), parse_time(flt["to"])
        hits = [
            ln
            for ln in sorted(data.logs, key=lambda x: x.ts)
            if (not services or ln.service in services) and lo <= ln.ts < hi
        ]
        offset, limit = int(page.get("cursor", 0)), int(page.get("limit", 10))
        chunk = hits[offset : offset + limit]
        events = [
            {"id": f"AQ{offset + i}", "type": "log", "attributes": {
                "timestamp": iso(ln.ts), "service": ln.service, "host": ln.host,
                "status": STATUS[ln.level], "message": ln.msg}}
            for i, ln in enumerate(chunk)
        ]  # fmt: skip
        more = offset + limit < len(hits)
        return {"data": events, "meta": {"page": {"after": str(offset + limit)} if more else {}}}

    @app.get("/api/v1/query")
    async def dd_metrics(
        query: str,
        from_: int = Query(alias="from"),
        to: int = 0,
        api: str | None = Header(default=None, alias="DD-API-KEY"),
        app_key: str | None = Header(default=None, alias="DD-APPLICATION-KEY"),
    ) -> dict[str, Any]:
        need_dd(api, app_key)
        m = re.search(r"incident\.([\w]+)\{service:([\w-]+)\}", query)
        if not m or m.group(2) not in data.metrics or m.group(1) not in data.metrics[m.group(2)]:
            return {"series": []}
        values, points = data.metrics[m.group(2)][m.group(1)], []
        for i, v in enumerate(values):
            ts = int((data.start + timedelta(minutes=i)).timestamp())
            if v is not None and from_ <= ts < to:
                points.append([ts * 1000, v])
        return {
            "series": [
                {"metric": m.group(1), "scope": f"service:{m.group(2)}", "pointlist": points}
            ]
        }


def _github(app: FastAPI, data: Dataset) -> None:
    @app.get("/repos/{owner}/{repo}/deployments")
    async def gh_deployments(owner: str, repo: str, per_page: int = 30) -> list[dict[str, Any]]:
        found = sorted(deploys(data, repo), key=lambda c: c.ts, reverse=True)[:per_page]
        return [
            {"id": i, "sha": sha(c.ref), "ref": c.ref, "environment": "production",
             "description": c.note, "created_at": iso(c.ts)}
            for i, c in enumerate(found, 1)
        ]  # fmt: skip

    @app.get("/repos/{owner}/{repo}/actions/runs")
    async def gh_runs(owner: str, repo: str) -> dict[str, Any]:
        return {"total_count": 0, "workflow_runs": []}

    @app.get("/repos/{owner}/{repo}/commits/{commit}")
    async def gh_commit(owner: str, repo: str, commit: str) -> dict[str, Any]:
        change = next((c for c in deploys(data, repo) if sha(c.ref) == commit), None)
        if change is None:
            raise HTTPException(404, "Not Found")
        patch = f"@@ -1,3 +1,5 @@\n-# previous release\n+# {change.ref}: {change.note}\n"
        return {
            "sha": commit,
            "html_url": f"https://github.com/{owner}/{repo}/commit/{commit}",
            "commit": {"message": change.note},
            "files": [{"filename": f"services/{repo}/release.py", "status": "modified",
                       "additions": 1, "deletions": 1, "patch": patch}],
        }  # fmt: skip


def _gcp(app: FastAPI, data: Dataset) -> None:
    @app.post("/v2/entries:list")
    async def gcp_entries(
        body: dict[str, Any], authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        if authorization != f"Bearer {GCP_TOKEN}":
            raise HTTPException(401, "Unauthorized")
        flt = body.get("filter", "")
        lo = re.search(r'timestamp>="([^"]+)"', flt)
        hi = re.search(r'timestamp<"([^"]+)"', flt)
        entries = [
            {"insertId": c.ref, "timestamp": iso(c.ts),
             "resource": {"labels": {"service_name": c.service}},
             "protoPayload": {"methodName": GCP_METHOD[c.kind],
                              "resourceName": f"projects/mock/services/{c.service}",
                              "request": {"description": c.note},
                              "authenticationInfo": {"principalEmail": "release-bot@corp.example"}}}
            for c in sorted(data.changes, key=lambda x: x.ts)
            if c.kind != "deploy"
            and (not lo or c.ts >= parse_time(lo.group(1)))
            and (not hi or c.ts < parse_time(hi.group(1)))
        ]  # fmt: skip
        return {"entries": entries}


def make_app(data: Dataset, faults: Faults | None = None) -> FastAPI:
    app = FastAPI(title="mock infrastructure")
    _faults(app, faults or Faults())
    _datadog(app, data)
    _github(app, data)
    _gcp(app, data)
    return app
