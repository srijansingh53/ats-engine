"""ATS engine: Flask app factory."""
from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import config
from .engine.pipeline import score_resume
from .llm import ClaudeLLM, LLMError
from .parsing import ParseError, parse_resume
from .validation import ValidationError, clean_jd

log = logging.getLogger("ats")
DEFAULT_STATIC = Path(__file__).resolve().parents[2] / "frontend" / "dist"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


def _configure_logging():
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(llm_factory=None, static_dir: str | os.PathLike | None = None, testing: bool = False) -> Flask:
    _configure_logging()
    static = Path(static_dir or os.environ.get("STATIC_DIR") or DEFAULT_STATIC)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
    app.config["RATELIMIT_ENABLED"] = not testing and config.RATE_LIMIT_ENABLED
    # Trust X-Forwarded-For / -Proto from the platform's load balancer (Render, Fly, Railway)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=config.TRUSTED_PROXIES, x_proto=config.TRUSTED_PROXIES)

    limiter = Limiter(get_remote_address, app=app, storage_uri=config.RATE_LIMIT_STORAGE,
                      headers_enabled=True, strategy="moving-window")
    app.extensions["ats_limiter"] = limiter  # decorators hold only a weak reference
    state: dict = {}

    def llm():
        if "llm" not in state:
            state["llm"] = (llm_factory or ClaudeLLM)()
        return state["llm"]

    # ---------- request lifecycle ----------

    @app.before_request
    def _start():
        g.rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        g.t0 = time.perf_counter()
        if request.path.startswith("/api/") and request.path != "/api/health" and config.ACCESS_TOKEN:
            sent = request.headers.get("X-Access-Token", "")
            if not hmac.compare_digest(sent, config.ACCESS_TOKEN):
                return jsonify(error="Access token required."), 401
        return None

    @app.after_request
    def _finish(resp):
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers["X-Request-ID"] = g.get("rid", "")
        if request.path.startswith("/assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        if request.path.startswith("/api/"):
            ms = (time.perf_counter() - g.get("t0", time.perf_counter())) * 1000
            log.info("rid=%s %s %s %s %.0fms", g.get("rid"), request.method, request.path, resp.status_code, ms)
        return resp

    # ---------- errors (never leak internals to the client) ----------

    @app.errorhandler(LLMError)
    def _llm_err(e):
        log.error("rid=%s LLM error: %s", g.get("rid"), e)
        if "not set" in str(e):
            return jsonify(error="Scoring is not configured on this server (missing API key)."), 503
        if "cut off" in str(e):
            return jsonify(error=str(e)), 502
        return jsonify(error="The scoring model is unavailable right now. Please try again in a minute.",
                       request_id=g.get("rid")), 502

    @app.errorhandler(ParseError)
    @app.errorhandler(ValidationError)
    def _bad_input(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(413)
    def _too_big(_):
        return jsonify(error=f"File too large (max {config.MAX_UPLOAD_MB} MB)."), 413

    @app.errorhandler(429)
    def _rate(e):
        return jsonify(error=f"Too many requests ({e.description}). Please wait and try again."), 429

    @app.errorhandler(HTTPException)
    def _http(e):
        return jsonify(error=e.description), e.code

    @app.errorhandler(Exception)
    def _unhandled(e):
        log.exception("rid=%s unhandled error", g.get("rid"))
        return jsonify(error="Something went wrong.", request_id=g.get("rid")), 500

    # ---------- API ----------

    @app.get("/api/health")
    @limiter.exempt
    def health():
        return jsonify(ok=True, llm_configured=bool(os.environ.get("ANTHROPIC_API_KEY")) or llm_factory is not None,
                       auth_required=bool(config.ACCESS_TOKEN))

    @app.get("/api/config")
    def get_config():
        return jsonify(weights=config.WEIGHTS, dimensions=config.DIMENSION_NAMES, skill_cutoff=config.SKILL_CUTOFF)

    @app.post("/api/jd/extract")
    @limiter.limit(config.RATE_LIMIT_EXTRACT)
    def extract_jd():
        body = request.get_json(silent=True) or {}
        text = (body.get("jd_text") or "").strip()
        if len(text) < 50:
            raise ValidationError("Paste the full job description (at least 50 characters).")
        if len(text) > config.MAX_JD_CHARS:
            raise ValidationError(f"Job description is too long (max {config.MAX_JD_CHARS:,} characters).")
        jd = clean_jd(llm().extract_jd(text))
        return jsonify(jd=jd)

    @app.post("/api/score")
    @limiter.limit(config.RATE_LIMIT_SCORE)
    def score():
        f = request.files.get("resume")
        if not f:
            raise ValidationError("Attach a resume file (PDF, DOCX or TXT).")
        jd_text = (request.form.get("jd_text") or "").strip()[: config.MAX_JD_CHARS]
        jd_json = request.form.get("jd")
        if jd_json:
            try:
                jd = json.loads(jd_json)
            except json.JSONDecodeError as exc:
                raise ValidationError("Invalid JD requirements JSON.") from exc
        elif len(jd_text) >= 50:
            jd = llm().extract_jd(jd_text)
        else:
            raise ValidationError("Paste the job description.")
        jd = clean_jd(jd)
        level = request.form.get("level")
        if level in config.LEVELS:
            jd["level"] = level
        parsed = parse_resume(f.filename, f.read())
        if parsed.char_count < 200:
            return jsonify(score_resume(jd, {}, parsed, jd_text))
        analysis = llm().analyze(parsed.text[: config.MAX_RESUME_CHARS], jd)
        result = score_resume(jd, analysis, parsed, jd_text)
        result["jd"] = jd
        return jsonify(result)

    # ---------- SPA ----------

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    @limiter.exempt
    def spa(path):
        if path.startswith("api/"):
            return jsonify(error="Not found"), 404
        if static.is_dir():
            target = (static / path).resolve()
            if path and target.is_file() and static.resolve() in target.parents:
                return send_from_directory(static, path)
            if (static / "index.html").is_file():
                return send_from_directory(static, "index.html")
        return jsonify(message="ATS engine API. Build the frontend to serve the UI here."), 200

    return app
