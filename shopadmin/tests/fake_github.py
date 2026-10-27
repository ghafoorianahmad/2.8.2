"""v2.11.0: an in-memory GitHub (Git Data API subset) behind ``httpx.MockTransport``.
Tests and the UI audits publish here — never to the real site repository."""
from __future__ import annotations

import base64
import hashlib
import json

import httpx

TOKEN = "github_pat_TEST_ONLY_not_a_real_token"


def _sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class FakeGitHub:
    def __init__(self, repo: str = "ghafoorianahmad/asr-ertebatat-2", branch: str = "main",
                 *, files: dict[str, bytes] | None = None, can_write: bool = True,
                 can_dispatch: bool = True):
        self.repo, self.branch = repo, branch
        self.can_write, self.can_dispatch = can_write, can_dispatch
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.commits: dict[str, dict] = {}
        self.dispatches: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.auth_seen: set[str] = set()
        self.race = False          # the next ref update fails (someone pushed meanwhile)
        tree = {path: self._blob(data) for path, data in (files or {}).items()}
        self.head = self._commit(tree, "initial", [])

    # ---- storage ------------------------------------------------------------------------
    def _blob(self, data: bytes) -> str:
        sha = _sha(data)
        self.blobs[sha] = data
        return sha

    def _tree(self, entries: dict[str, str]) -> str:
        sha = hashlib.sha1(json.dumps(sorted(entries.items())).encode()).hexdigest()
        self.trees[sha] = dict(entries)
        return sha

    def _commit(self, entries: dict[str, str], message: str, parents: list[str]) -> str:
        tree = self._tree(entries)
        sha = hashlib.sha1(f"{tree}{message}{parents}{len(self.commits)}".encode()).hexdigest()
        self.commits[sha] = {"tree": tree, "message": message, "parents": parents}
        return sha

    def files(self) -> dict[str, bytes]:
        """The branch's files now."""
        tree = self.trees[self.commits[self.head]["tree"]]
        return {path: self.blobs[sha] for path, sha in tree.items()}

    def messages(self) -> list[str]:
        out, sha = [], self.head
        while sha:
            out.append(self.commits[sha]["message"])
            parents = self.commits[sha]["parents"]
            sha = parents[0] if parents else ""
        return out

    # ---- HTTP -----------------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        self.auth_seen.add(request.headers.get("Authorization", ""))

        def reply(status: int, payload=None) -> httpx.Response:
            if payload is None:
                return httpx.Response(status, request=request)
            return httpx.Response(status, json=payload, request=request)

        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return reply(401, {"message": "Bad credentials"})
        base = f"/repos/{self.repo}"
        if not path.startswith(base):
            return reply(404, {"message": "Not Found"})
        rest = path[len(base):]
        body = json.loads(request.content) if request.content else {}
        if rest == "" and request.method == "GET":
            return reply(200, {"full_name": self.repo, "permissions": {"push": self.can_write}})
        if rest == f"/branches/{self.branch}":
            return reply(200, {"name": self.branch, "commit": {"sha": self.head}})
        if rest == f"/git/ref/heads/{self.branch}":
            return reply(200, {"object": {"sha": self.head}})
        if rest.startswith("/git/commits/") and request.method == "GET":
            commit = self.commits.get(rest.rsplit("/", 1)[1])
            return reply(200, {"tree": {"sha": commit["tree"]}}) if commit else reply(404, {})
        if rest.startswith("/git/trees/") and request.method == "GET":
            tree = self.trees.get(rest.rsplit("/", 1)[1])
            if tree is None:
                return reply(404, {})
            return reply(200, {"tree": [{"path": p, "type": "blob", "sha": s}
                                        for p, s in sorted(tree.items())]})
        if rest.startswith("/contents/") and request.method == "GET":
            data = self.files().get(rest[len("/contents/"):])
            if data is None:
                return reply(404, {"message": "Not Found"})
            return reply(200, {"encoding": "base64", "content": base64.b64encode(data).decode(),
                               "sha": _sha(data)})
        if not self.can_write and request.method != "GET":
            return reply(403, {"message": "Resource not accessible by personal access token"})
        if rest == "/git/blobs" and request.method == "POST":
            return reply(201, {"sha": self._blob(base64.b64decode(body["content"]))})
        if rest == "/git/trees" and request.method == "POST":
            entries = dict(self.trees[body["base_tree"]])
            for entry in body["tree"]:
                if entry["sha"] is None:
                    entries.pop(entry["path"], None)
                else:
                    entries[entry["path"]] = entry["sha"]
            return reply(201, {"sha": self._tree(entries)})
        if rest == "/git/commits" and request.method == "POST":
            tree = self.trees[body["tree"]]
            return reply(201, {"sha": self._commit(tree, body["message"], body["parents"])})
        if rest == f"/git/refs/heads/{self.branch}" and request.method == "PATCH":
            commit = self.commits[body["sha"]]
            if self.race or commit["parents"] != [self.head] or body.get("force"):
                self.race = False
                return reply(422, {"message": "Update is not a fast forward"})
            self.head = body["sha"]
            return reply(200, {"object": {"sha": self.head}})
        if rest.startswith("/actions/workflows/") and request.method == "POST":
            if not self.can_dispatch:
                return reply(403, {"message": "Resource not accessible by personal access token"})
            self.dispatches.append(body.get("ref", ""))
            return reply(204)
        return reply(404, {"message": "Not Found"})
