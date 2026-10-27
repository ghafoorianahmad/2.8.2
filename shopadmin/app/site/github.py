"""v2.11.0 «انتشار در سایت»: catalog.json + photos committed straight to the
site's GitHub repository with the GitHub REST API (Git Data API), from THIS
computer. Nothing goes through the shop server.

* One commit per publish on top of the branch head; the branch is moved with
  ``force: false`` (never overwrites a change made elsewhere meanwhile).
* Only files whose content differs are uploaded (git blob hash compared).
* ``previous`` remembers each written path's old blob (or None): «برگرداندن
  انتشار قبلی» is a new commit putting those blobs back (they stay in git).
* After the commit, the site's own manual workflow «Deploy static site to
  ArvanCloud Object Storage» is started (needs the token's Actions permission;
  without it the files are in GitHub and the owner starts the workflow).

The token is never logged, shown or put in an error text. Tests use a mock
transport only — development never touches the real repository.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

import httpx

API = "https://api.github.com"
DEFAULT_REPO = "ghafoorianahmad/asr-ertebatat-2"
DEFAULT_BRANCH = "main"
DEPLOY_WORKFLOW = "deploy-arvan.yml"
TIMEOUT = 60.0


class GitHubError(Exception):
    """A Persian message for the user (never the token)."""

    def __init__(self, message: str, *, status: int = 0):
        super().__init__(message)
        self.status = status


def blob_sha(data: bytes) -> str:
    """The git object id of a file's content (what GitHub's tree lists)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _message(status: int, body: str = "") -> str:
    if status == 401:
        return "توکن GitHub نادرست است یا تاریخش گذشته؛ توکن تازه بسازید و دوباره وارد کنید."
    if status == 403:
        if "rate limit" in body.lower():
            return "GitHub موقتاً درخواست‌ها را محدود کرده؛ چند دقیقهٔ دیگر دوباره امتحان کنید."
        return "این توکن اجازهٔ این کار را ندارد (دسترسی «Contents: Read and write» لازم است)."
    if status == 404:
        return "مخزن سایت پیدا نشد یا توکن به آن دسترسی ندارد."
    if status in (409, 422):
        return ("سایت در همین لحظه از جای دیگری تغییر کرد؛ چند ثانیه بعد دوباره «انتشار» را "
                "بزنید.")
    if status >= 500:
        return "سرور GitHub پاسخ نداد؛ کمی بعد دوباره امتحان کنید."
    return "GitHub این درخواست را نپذیرفت."


class GitHubPublisher:
    def __init__(self, token: str, repo: str = DEFAULT_REPO, branch: str = DEFAULT_BRANCH, *,
                 transport: Optional[httpx.BaseTransport] = None, timeout: float = TIMEOUT):
        if not token or not token.strip():
            raise GitHubError("توکن GitHub وارد نشده است.")
        self.repo = repo.strip().strip("/")
        self.branch = branch.strip() or DEFAULT_BRANCH
        self._client = httpx.Client(
            base_url=API, timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {token.strip()}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "ShopAdmin-site"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    # ---- low level ---------------------------------------------------------------------
    def _call(self, method: str, path: str, *, json=None, ok=(200, 201)) -> dict:
        try:
            response = self._client.request(method, path, json=json)
        except httpx.TimeoutException:
            raise GitHubError("پاسخ GitHub دیر رسید؛ اتصال اینترنت را بررسی کنید.") from None
        except httpx.HTTPError:
            raise GitHubError("اتصال به GitHub برقرار نشد؛ اینترنت این رایانه را بررسی کنید.") \
                from None
        if response.status_code not in ok:
            raise GitHubError(_message(response.status_code, response.text[:300]),
                              status=response.status_code)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise GitHubError("پاسخ GitHub خوانا نبود.") from None

    def _repo(self, suffix: str) -> str:
        return f"/repos/{self.repo}{suffix}"

    # ---- checks ------------------------------------------------------------------------
    def test_connection(self) -> dict:
        """{"repo", "can_write", "branch"}; raises GitHubError with the reason."""
        info = self._call("GET", self._repo(""))
        can_write = bool((info.get("permissions") or {}).get("push"))
        self._call("GET", self._repo(f"/branches/{self.branch}"))
        if not can_write:
            raise GitHubError("توکن فقط اجازهٔ خواندن دارد؛ «Contents: Read and write» لازم است.")
        return {"repo": info.get("full_name") or self.repo, "can_write": can_write,
                "branch": self.branch}

    def read_file(self, path: str) -> Optional[bytes]:
        """A file of the branch (None when it does not exist)."""
        try:
            data = self._call("GET", self._repo(f"/contents/{path}?ref={self.branch}"))
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        if data.get("encoding") == "base64" and data.get("content") is not None:
            return base64.b64decode(data["content"])
        sha = data.get("sha")
        if not sha:
            return None
        blob = self._call("GET", self._repo(f"/git/blobs/{sha}"))
        return base64.b64decode(blob.get("content") or "")

    def _head(self) -> tuple[str, str]:
        ref = self._call("GET", self._repo(f"/git/ref/heads/{self.branch}"))
        head = ref["object"]["sha"]
        commit = self._call("GET", self._repo(f"/git/commits/{head}"))
        return head, commit["tree"]["sha"]

    def tree(self) -> dict[str, str]:
        """path -> blob sha of every file of the branch."""
        _head, tree_sha = self._head()
        tree = self._call("GET", self._repo(f"/git/trees/{tree_sha}?recursive=1"))
        return {e["path"]: e["sha"] for e in tree.get("tree") or [] if e.get("type") == "blob"}

    # ---- publish / roll back ------------------------------------------------------------
    def _commit(self, entries: list[dict], message: str, head: str, base_tree: str) -> str:
        tree = self._call("POST", self._repo("/git/trees"),
                          json={"base_tree": base_tree, "tree": entries})
        commit = self._call("POST", self._repo("/git/commits"),
                            json={"message": message, "tree": tree["sha"], "parents": [head]})
        self._call("PATCH", self._repo(f"/git/refs/heads/{self.branch}"),
                   json={"sha": commit["sha"], "force": False})
        return commit["sha"]

    def publish(self, files: dict[str, bytes], message: str) -> dict:
        """Commit the files that differ. Returns {"commit" (None = nothing to do),
        "previous": {path: old blob sha or None}, "written", "unchanged"}."""
        head, base_tree = self._head()
        tree = self._call("GET", self._repo(f"/git/trees/{base_tree}?recursive=1"))
        remote = {e["path"]: e["sha"] for e in tree.get("tree") or [] if e.get("type") == "blob"}
        entries, previous, unchanged = [], {}, 0
        for path, data in sorted(files.items()):
            if remote.get(path) == blob_sha(data):
                unchanged += 1
                continue
            blob = self._call("POST", self._repo("/git/blobs"),
                              json={"content": base64.b64encode(data).decode("ascii"),
                                    "encoding": "base64"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            previous[path] = remote.get(path)
        if not entries:
            return {"commit": None, "previous": {}, "written": 0, "unchanged": unchanged}
        commit = self._commit(entries, message, head, base_tree)
        return {"commit": commit, "previous": previous, "written": len(entries),
                "unchanged": unchanged}

    def rollback(self, previous: dict[str, Optional[str]], message: str) -> str:
        """Put the remembered blobs back (a path that did not exist is removed)."""
        if not previous:
            raise GitHubError("چیزی برای برگرداندن نیست.")
        head, base_tree = self._head()
        entries = [{"path": path, "mode": "100644", "type": "blob", "sha": sha}
                   for path, sha in sorted(previous.items())]
        return self._commit(entries, message, head, base_tree)

    def start_deploy(self, workflow: str = DEPLOY_WORKFLOW) -> tuple[bool, str]:
        """Start the site's deploy workflow. (started?, Persian note)."""
        try:
            self._call("POST", self._repo(f"/actions/workflows/{workflow}/dispatches"),
                       json={"ref": self.branch}, ok=(204,))
        except GitHubError as exc:
            if exc.status in (403, 404):
                return False, ("فایل‌ها در GitHub ثبت شد ولی توکن اجازهٔ اجرای «Deploy» را ندارد؛ "
                               "در GitHub › Actions گردش‌کار «Deploy static site…» را دستی اجرا "
                               "کنید یا به توکن دسترسی «Actions: Read and write» بدهید.")
            return False, f"فایل‌ها در GitHub ثبت شد ولی اجرای «Deploy» شروع نشد: {exc}"
        return True, "انتشار در سایت شروع شد؛ معمولاً چند دقیقه بعد در سایت دیده می‌شود."
