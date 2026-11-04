"""Validate and bound the JD requirements a client sends (it may be edited in the UI)."""
from __future__ import annotations

from . import config

MAX_ITEMS = 40
MAX_TEXT = 300


class ValidationError(ValueError):
    pass


def _s(v, limit=MAX_TEXT) -> str:
    return str(v or "").strip()[:limit]


def _imp(v) -> str:
    return "required" if str(v).lower() == "required" else "preferred"


def _num(v, lo=0.0, hi=40.0):
    if v in (None, ""):
        return None
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def _req(v):
    if not isinstance(v, dict) or not _s(v.get("text")):
        return None
    return {"text": _s(v.get("text")), "importance": _imp(v.get("importance"))}


def clean_jd(jd) -> dict:
    if not isinstance(jd, dict):
        raise ValidationError("JD requirements must be an object.")
    level = jd.get("level") if jd.get("level") in config.LEVELS else "entry"
    comps = []
    for c in (jd.get("competencies") or [])[:MAX_ITEMS]:
        if not isinstance(c, dict) or not _s(c.get("name")):
            continue
        alts = [_s(a, 80) for a in (c.get("alternatives") or []) if _s(a, 80)][:10]
        comps.append({"name": _s(c.get("name"), 120), "alternatives": alts or [_s(c.get("name"), 120)],
                      "importance": _imp(c.get("importance"))})
    exps = []
    for x in (jd.get("experience_requirements") or [])[:MAX_ITEMS]:
        r = _req(x)
        if r:
            r["min_yoe"] = _num(x.get("min_yoe"))
            exps.append(r)
    cutoff = _num(jd.get("skill_cutoff"), 0, 10)
    req_t = _num(jd.get("required_threshold"), 0, 100)
    return {
        "title": _s(jd.get("title"), 120),
        "level": level,
        "min_yoe": _num(jd.get("min_yoe")),
        "competencies": comps,
        "experience_requirements": exps,
        "degree": _req(jd.get("degree")),
        "college_preference": _req(jd.get("college_preference")),
        "certifications": [r for r in (_req(c) for c in (jd.get("certifications") or [])[:MAX_ITEMS]) if r],
        "red_flags": [_s(f) for f in (jd.get("red_flags") or [])[:20] if _s(f)],
        "location": _s(jd.get("location"), 120) or None,
        "skill_cutoff": cutoff if cutoff is not None else config.SKILL_CUTOFF[level],
        "required_threshold": req_t if req_t is not None else config.REQUIRED_THRESHOLD,
    }
