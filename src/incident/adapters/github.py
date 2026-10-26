"""GitHub: deployments and deploy workflow runs as changes, and commit diffs as code evidence."""

import re
from datetime import datetime

from incident.adapters.ports import Http
from incident.models import Change, Strict
from incident.redact import redact

DEPLOY_WORKFLOW = re.compile(r"deploy|release|rollout", re.I)
PATCH_CHARS = 1500


class FileChange(Strict):
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str = ""


class CodeChange(Strict):
    """What a commit really changed: a label like 'minor copy change' proves little, a diff does."""

    sha: str
    message: str
    files: list[FileChange]
    url: str


def _release_ref(d: dict) -> str:  # type: ignore[type-arg]
    """A release tag (anything with a digit that is not a bare branch) beats a bare short sha."""
    ref = d.get("ref") or ""
    return ref if re.search(r"\d", ref) and ref not in ("main", "master") else d["sha"][:7]


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class GitHub:
    def __init__(
        self, http: Http, repo: str, token: str | None = None, service: str | None = None
    ) -> None:
        self.http, self.repo = http, repo
        self.service = service or repo.split("/")[-1]  # which service this repository deploys
        self.base = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Accept": "application/vnd.github+json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        }

    async def changes(self, start: datetime, end: datetime) -> list[Change]:
        out = await self._deployments(start, end) + await self._workflow_runs(start, end)
        return sorted(out, key=lambda c: c.ts)

    async def _deployments(self, start: datetime, end: datetime) -> list[Change]:
        url, params = f"{self.base}/deployments", {"per_page": 100}
        out = []
        for d in await self.http.request("GET", url, headers=self.headers, params=params):
            when = _when(d["created_at"])
            if start <= when < end:
                note = d.get("description") or f"deployment to {d.get('environment', 'unknown')}"
                out.append(
                    Change(
                        ts=when,
                        kind="deploy",
                        service=self.service,
                        ref=_release_ref(d),
                        note=redact(note),
                        source="github",
                        url=f"https://github.com/{self.repo}/commit/{d['sha']}",
                    )
                )
        return out

    async def _workflow_runs(self, start: datetime, end: datetime) -> list[Change]:
        url, params = f"{self.base}/actions/runs", {"per_page": 100, "status": "success"}
        runs = await self.http.request("GET", url, headers=self.headers, params=params)
        out = []
        for r in runs.get("workflow_runs", []):
            when = _when(r["created_at"])
            if DEPLOY_WORKFLOW.search(r.get("name", "")) and start <= when < end:
                lines = (r.get("head_commit") or {}).get("message", "").splitlines()
                out.append(
                    Change(
                        ts=when,
                        kind="deploy",
                        service=self.service,
                        ref=r["head_sha"][:7],
                        note=redact(f"{r['name']}: {lines[0] if lines else ''}"),
                        source="github-actions",
                        url=r["html_url"],
                    )
                )
        return out

    async def commit(self, sha: str) -> CodeChange:
        c = await self.http.request("GET", f"{self.base}/commits/{sha}", headers=self.headers)
        files = [
            FileChange(
                filename=f["filename"],
                status=f["status"],
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
                patch=redact(f.get("patch", ""))[:PATCH_CHARS],
            )
            for f in c.get("files", [])
        ]
        return CodeChange(
            sha=c["sha"], message=redact(c["commit"]["message"]), files=files, url=c["html_url"]
        )
