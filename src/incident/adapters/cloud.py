"""AWS CloudFormation stack events and GCP Cloud Audit Logs, mapped to changes.

The mappers are pure functions over the providers' documented response shapes, so they are
tested from recorded responses without credentials. The fetch classes only add the transport.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from incident.adapters.ports import Http
from incident.models import Change, ChangeKind
from incident.redact import redact

CFN_DEPLOY = {"AWS::ECS::Service", "AWS::Lambda::Function", "AWS::ApiGateway::Deployment"}
CFN_DONE = {
    "UPDATE_COMPLETE",
    "CREATE_COMPLETE",
    "UPDATE_FAILED",
    "UPDATE_ROLLBACK_COMPLETE",
    "ROLLBACK_COMPLETE",
}
GCP_DEPLOY = ("ReplaceService", "CreateRevision", "UpdateService", "Deployments.insert")
GCP_KINDS: tuple[tuple[str, ChangeKind], ...] = (
    ("RuntimeConfig", "flag"),
    ("Sql", "migration"),
    ("SecretManager", "config"),
)


def _gcp_kind(method: str) -> ChangeKind:
    if any(m in method for m in GCP_DEPLOY):
        return "deploy"
    return next((kind for key, kind in GCP_KINDS if key in method), "config")


def map_stack_events(
    resp: dict[str, Any], service_of: Callable[[str], str], region: str = "us-east-1"
) -> list[Change]:
    out = []
    for e in resp.get("StackEvents", []):
        status, rtype = e.get("ResourceStatus", ""), e.get("ResourceType", "")
        if status not in CFN_DONE or not (
            rtype == "AWS::CloudFormation::Stack" or rtype in CFN_DEPLOY
        ):
            continue
        kind: ChangeKind = "deploy" if rtype in CFN_DEPLOY else "config"
        reason = redact(e.get("ResourceStatusReason") or "")
        link = (
            f"https://{region}.console.aws.amazon.com/cloudformation/home?region={region}"
            f"#/stacks/events?stackId={e['StackId']}"
        )
        out.append(
            Change(
                ts=e["Timestamp"],
                kind=kind,
                service=service_of(e["StackName"]),
                ref=e["EventId"][:24],
                note=f"{e['LogicalResourceId']} {status}" + (f": {reason}" if reason else ""),
                source="cloudformation",
                url=link,
            )
        )
    return sorted(out, key=lambda c: c.ts)


def map_audit_entries(resp: dict[str, Any], service_of: Callable[[str], str]) -> list[Change]:
    out = []
    for e in resp.get("entries", []):
        p = e.get("protoPayload", {})
        method = p.get("methodName", "")
        labels = (e.get("resource") or {}).get("labels", {})
        name = (
            labels.get("service_name")
            or labels.get("function_name")
            or p.get("resourceName", "").split("/")[-1]
        )
        kind = _gcp_kind(method)
        what = (p.get("request") or {}).get("description")
        # The acting principal's email is deliberately not copied (personal data, not needed).
        out.append(
            Change(
                ts=e["timestamp"],
                kind=kind,
                service=service_of(name),
                ref=e["insertId"][:40],
                note=redact(
                    method.rsplit(".", 1)[-1]
                    + f" on {p.get('resourceName', name)}"
                    + (f": {what}" if what else "")
                ),
                source="gcp-audit-logs",
                url=f"https://console.cloud.google.com/logs/query;query=insertId%3D%22{e['insertId']}%22",
            )
        )
    return sorted(out, key=lambda c: c.ts)


class CloudFormation:
    """`client` is a boto3 CloudFormation client (injected, so tests need no AWS)."""

    def __init__(
        self, client: Any, stacks: list[str], service_of: Callable[[str], str] = lambda s: s
    ) -> None:
        self.client, self.stacks, self.service_of = client, stacks, service_of

    async def changes(self, start: datetime, end: datetime) -> list[Change]:
        out: list[Change] = []
        for stack in self.stacks:
            resp = await asyncio.to_thread(self.client.describe_stack_events, StackName=stack)
            out += [c for c in map_stack_events(resp, self.service_of) if start <= c.ts < end]
        return sorted(out, key=lambda c: c.ts)


class GcpAuditLogs:
    def __init__(
        self, http: Http, project: str, token: str, service_of: Callable[[str], str] = lambda s: s
    ) -> None:
        self.http, self.project, self.service_of = http, project, service_of
        self.headers = {"Authorization": f"Bearer {token}"}

    async def changes(self, start: datetime, end: datetime) -> list[Change]:
        flt = (
            f'logName="projects/{self.project}/logs/cloudaudit.googleapis.com%2Factivity" '
            f'AND timestamp>="{start.isoformat()}" AND timestamp<"{end.isoformat()}"'
        )
        body = {
            "resourceNames": [f"projects/{self.project}"],
            "filter": flt,
            "pageSize": 200,
            "orderBy": "timestamp asc",
        }
        resp = await self.http.request(
            "POST",
            "https://logging.googleapis.com/v2/entries:list",
            headers=self.headers,
            json=body,
        )
        return map_audit_entries(resp, self.service_of)
