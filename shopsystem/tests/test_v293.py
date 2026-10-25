"""v2.9.3: ShopSystem ``--grant-db`` («دادن دسترسی به این دیتابیس» in the server
setup) always answers with one JSON line, without the password."""
from __future__ import annotations

import json

import launcher


def test_grant_db_without_settings_answers_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(launcher, "load_env_file", lambda: False)
    code = launcher.main(["--data-dir", str(tmp_path), "--grant-db"])
    answer = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code != 0 and answer == {"ok": False, "error": "no .env"}


def test_grant_db_failure_is_reported_in_persian(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(launcher, "load_env_file", lambda: True)
    monkeypatch.setattr(launcher, "grant_db", lambda: (_ for _ in ()).throw(
        RuntimeError("boom")))
    code = launcher.main(["--data-dir", str(tmp_path), "--grant-db"])
    answer = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 1 and answer["ok"] is False and "RuntimeError" in answer["message"]
