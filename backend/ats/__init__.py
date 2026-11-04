"""ATS engine: Flask app factory."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import config
from .engine.pipeline import score_resume
from .llm import ClaudeLLM, LLMError
from .parsing import ParseError, parse_resume

log = logging.getLogger("ats")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
DEFAULT_STATIC = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(llm_factory=None, static_dir: str | os.PathLike | None = None) -> Flask:
    static = Path(static_dir or os.environ.get("STATIC_DIR") or DEFAULT_STATIC)
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
    state: dict = {}

    def llm():
        if "llm" not in state:
            state["llm"] = (llm_factory or ClaudeLLM)()
        return state["llm"]

    @app.errorhandler(LLMError)
    def _llm_err(e):
        log.error("LLM error: %s", e)
        code = 503 if "not set" in str(e) else 502
        return jsonify(error=str(e)), code

    @app.errorhandler(ParseError)
    def _parse_err(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(413)
    def _too_big(_):
        return jsonify(error=f"File too large (max {config.MAX_UPLOAD_MB} MB)"), 413

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, llm_configured=bool(os.environ.get("ANTHROPIC_API_KEY")) or llm_factory is not None,
                       model=config.ANTHROPIC_MODEL)

    @app.get("/api/config")
    def get_config():
        return jsonify(weights=config.WEIGHTS, dimensions=config.DIMENSION_NAMES, skill_cutoff=config.SKILL_CUTOFF)

    @app.post("/api/jd/extract")
    def extract_jd():
        body = request.get_json(silent=True) or {}
        text = (body.get("jd_text") or "").strip()
        if len(text) < 50:
            return jsonify(error="Paste the full job description (at least 50 characters)."), 400
        jd = llm().extract_jd(text)
        jd.setdefault("skill_cutoff", config.SKILL_CUTOFF.get(jd.get("level", "entry"), 6.0))
        return jsonify(jd=jd)

    @app.post("/api/score")
    def score():
        f = request.files.get("resume")
        if not f:
            return jsonify(error="Attach a resume file (PDF, DOCX or TXT)."), 400
        jd_text = (request.form.get("jd_text") or "").strip()
        jd_json = request.form.get("jd")
        if jd_json:
            try:
                jd = json.loads(jd_json)
            except json.JSONDecodeError:
                return jsonify(error="Invalid JD requirements JSON."), 400
        elif len(jd_text) >= 50:
            jd = llm().extract_jd(jd_text)
        else:
            return jsonify(error="Paste the job description."), 400
        level = request.form.get("level")
        if level in config.LEVELS:
            jd["level"] = level
        parsed = parse_resume(f.filename, f.read())
        if parsed.char_count < 200:
            return jsonify(score_resume(jd, {}, parsed, jd_text))
        analysis = llm().analyze(parsed.text, jd)
        result = score_resume(jd, analysis, parsed, jd_text)
        result["jd"] = jd
        result["resume"] = analysis.get("resume")
        return jsonify(result)

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            return jsonify(error="Not found"), 404
        if static.is_dir():
            target = static / path
            if path and target.is_file():
                return send_from_directory(static, path)
            if (static / "index.html").is_file():
                return send_from_directory(static, "index.html")
        return jsonify(message="ATS engine API. Build the frontend to serve the UI here."), 200

    return app
