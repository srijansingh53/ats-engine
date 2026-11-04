import io
import json

from conftest import JD, RESUME_TEXT, FakeLLM

from ats import config, create_app
from ats.llm import LLMError
from ats.validation import clean_jd


def form(**extra):
    d = {"jd": json.dumps(JD), "resume": (io.BytesIO(RESUME_TEXT.encode()), "r.txt")}
    d.update(extra)
    return d


def test_rate_limit_on_score(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RATE_LIMIT_SCORE", "2 per minute")
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    c = create_app(llm_factory=FakeLLM, static_dir=tmp_path).test_client()
    codes = [c.post("/api/score", data=form(), content_type="multipart/form-data").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert c.get("/api/health").status_code == 200  # health is exempt


def test_access_token(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ACCESS_TOKEN", "s3cret")
    c = create_app(llm_factory=FakeLLM, static_dir=tmp_path, testing=True).test_client()
    assert c.get("/api/health").get_json()["auth_required"] is True
    assert c.post("/api/score", data=form(), content_type="multipart/form-data").status_code == 401
    r = c.post("/api/score", data=form(), content_type="multipart/form-data", headers={"X-Access-Token": "s3cret"})
    assert r.status_code == 200


def test_security_headers_and_request_id(tmp_path):
    c = create_app(llm_factory=FakeLLM, static_dir=tmp_path, testing=True).test_client()
    r = c.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Request-ID"]
    assert r.headers["Cache-Control"] == "no-store"


def test_llm_error_is_not_leaked(tmp_path):
    class Boom(FakeLLM):
        def analyze(self, *a):
            raise LLMError("Claude API call failed: secret internal detail req_123")

    c = create_app(llm_factory=Boom, static_dir=tmp_path, testing=True).test_client()
    r = c.post("/api/score", data=form(), content_type="multipart/form-data")
    assert r.status_code == 502
    assert "secret" not in r.get_json()["error"]
    assert r.get_json()["request_id"]


def test_unhandled_error_is_generic(tmp_path):
    class Crash(FakeLLM):
        def analyze(self, *a):
            raise KeyError("boom")

    c = create_app(llm_factory=Crash, static_dir=tmp_path, testing=True).test_client()
    r = c.post("/api/score", data=form(), content_type="multipart/form-data")
    assert r.status_code == 500 and r.get_json()["error"] == "Something went wrong."


def test_fake_pdf_rejected(tmp_path):
    c = create_app(llm_factory=FakeLLM, static_dir=tmp_path, testing=True).test_client()
    r = c.post("/api/score", data=form(resume=(io.BytesIO(b"not a pdf" * 50), "cv.pdf")),
               content_type="multipart/form-data")
    assert r.status_code == 400 and "not a valid PDF" in r.get_json()["error"]


def test_jd_too_long(tmp_path):
    c = create_app(llm_factory=FakeLLM, static_dir=tmp_path, testing=True).test_client()
    r = c.post("/api/jd/extract", json={"jd_text": "x" * (config.MAX_JD_CHARS + 1)})
    assert r.status_code == 400


def test_clean_jd_bounds_and_defaults():
    dirty = {"level": "god", "competencies": [{"name": "x" * 500, "importance": "MUST"}] * 100,
             "red_flags": ["a"] * 50, "skill_cutoff": 99, "min_yoe": "abc"}
    jd = clean_jd(dirty)
    assert jd["level"] == "entry"
    assert len(jd["competencies"]) == 40 and len(jd["competencies"][0]["name"]) == 120
    assert jd["competencies"][0]["importance"] == "preferred"
    assert len(jd["red_flags"]) == 20
    assert jd["skill_cutoff"] == 10 and jd["min_yoe"] is None


def test_static_path_traversal_blocked(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    c = create_app(llm_factory=FakeLLM, static_dir=tmp_path, testing=True).test_client()
    r = c.get("/../../etc/passwd")
    assert b"root:" not in r.data
