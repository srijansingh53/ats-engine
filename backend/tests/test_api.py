import io
import json

import pytest
from conftest import JD, RESUME_TEXT, FakeLLM

from ats import create_app


@pytest.fixture
def client(tmp_path):
    fake = FakeLLM()
    app = create_app(llm_factory=lambda: fake, static_dir=tmp_path, testing=True)
    app.testing = True
    return app.test_client(), fake


def test_health(client):
    c, _ = client
    assert c.get("/api/health").get_json()["ok"] is True


def test_extract_jd(client):
    c, _ = client
    r = c.post("/api/jd/extract", json={"jd_text": "We need a senior backend engineer with Python " * 3})
    assert r.status_code == 200
    jd = r.get_json()["jd"]
    assert jd["skill_cutoff"] == 7.0
    assert jd["competencies"][0]["name"] == "Python"


def test_extract_jd_too_short(client):
    c, _ = client
    assert c.post("/api/jd/extract", json={"jd_text": "short"}).status_code == 400


def test_score_with_edited_jd(client):
    c, fake = client
    data = {"jd": json.dumps(JD), "jd_text": "",
            "resume": (io.BytesIO(RESUME_TEXT.encode()), "resume.txt")}
    r = c.post("/api/score", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] in ("PASS", "WOULD_BE_REJECTED")
    assert isinstance(body["score"], int)
    assert body["fixes"] and body["fixes"][0]["rank"] == 1
    assert fake.calls == 1  # JD given, only analysis called


def test_score_level_override(client):
    c, _ = client
    data = {"jd": json.dumps(JD), "level": "entry", "resume": (io.BytesIO(RESUME_TEXT.encode()), "r.txt")}
    body = c.post("/api/score", data=data, content_type="multipart/form-data").get_json()
    assert body["level"] == "entry"


def test_score_requires_file(client):
    c, _ = client
    assert c.post("/api/score", data={"jd": json.dumps(JD)}).status_code == 400


def test_unsupported_type(client):
    c, _ = client
    data = {"jd": json.dumps(JD), "resume": (io.BytesIO(b"abc"), "r.exe")}
    assert c.post("/api/score", data=data, content_type="multipart/form-data").status_code == 400


def test_missing_api_key_returns_503(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(static_dir=tmp_path, testing=True)
    r = app.test_client().post("/api/jd/extract", json={"jd_text": "x" * 80})
    assert r.status_code == 503
    assert "API key" in r.get_json()["error"]


def test_spa_fallback(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    app = create_app(llm_factory=FakeLLM, static_dir=tmp_path, testing=True)
    c = app.test_client()
    assert b"app" in c.get("/").data
    assert b"app" in c.get("/some/route").data
    assert c.get("/api/nope").status_code == 404
