"""Deterministic layers L1-L5. Pure functions of (jd, analysis, parsed doc, today)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .. import config
from ..parsing import ParsedDocument
from .dates import months_between, parse_ym, to_index, union_months

SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|staff|principal|architect|head)\b", re.I)
QUANTIFIED = re.compile(
    r"(\d+(\.\d+)?\s?(%|x\b|k\b|m\b|b\b|ms\b|sec|s\b|hrs?\b|hours|days|weeks|users|customers|clients|qps|rps|tps|"
    r"req|requests|cr\b|crore|lakh|million|billion|gb|tb|services|engineers|members))|([$₹€£]\s?\d)",
    re.I,
)


@dataclass
class Context:
    jd: dict
    analysis: dict
    parsed: ParsedDocument
    today: date
    jd_text: str = ""

    @property
    def level(self) -> str:
        lvl = (self.jd.get("level") or "entry").lower()
        return lvl if lvl in config.LEVELS else "entry"

    @property
    def resume(self) -> dict:
        return self.analysis.get("resume") or {}

    @property
    def roles(self) -> list[dict]:
        return self.resume.get("roles") or []


@dataclass
class Result:
    status: str
    level: str
    score: int
    band: str
    band_action: str
    yoe: float
    skill_gate: dict
    required_gate: dict
    knockouts: list[dict]
    dimensions: list[dict]
    penalties: list[dict]
    flags: list[str]
    competencies: list[dict] = field(default_factory=list)
    raw_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ---------- helpers ----------

def _role_interval(role: dict, today: date) -> tuple[int, int] | None:
    s, e = parse_ym(role.get("start"), today), parse_ym(role.get("end") or "present", today)
    if not s or not e:
        return None
    return to_index(s), to_index(e)


def relevant_yoe(ctx: Context) -> float:
    ft, intern = [], []
    for r in ctx.roles:
        if not r.get("is_software_role", True):
            continue
        iv = _role_interval(r, ctx.today)
        if not iv:
            continue
        kind = r.get("employment_type", "full_time")
        (intern if kind == "internship" else ft).append(iv)
    months = union_months(ft) + union_months(intern) * config.INTERNSHIP_YOE_MULTIPLIER[ctx.level]
    return round(months / 12, 1)


def _recency_factor(last_used: str | None, today: date) -> float:
    ym = parse_ym(last_used, today) if last_used else None
    if not ym:
        return 0.7
    ago = to_index((today.year, today.month)) - to_index(ym)
    for limit, factor in config.RECENCY_STEPS:
        if ago <= limit:
            return factor
    return config.RECENCY_OLD


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _rubric(ctx: Context, key: str) -> dict:
    r = (ctx.analysis.get("rubrics") or {}).get(key) or {}
    return {"score": _clamp(float(r.get("score", 0) or 0)), "evidence": r.get("evidence") or [],
            "gaps": r.get("gaps") or []}


def _paired(jd_items: list, an_items: list) -> list[tuple[dict, dict]]:
    """Pair JD items with analysis items by order (the LLM is asked to keep the same order)."""
    return [(item, (an_items[i] if i < len(an_items) else None) or {}) for i, item in enumerate(jd_items)]


# ---------- L2 ----------

def skill_gate(ctx: Context) -> tuple[dict, list[dict]]:
    comps = ctx.jd.get("competencies") or []
    rows, num, den = [], 0.0, 0.0
    for jd_c, an in _paired(comps, ctx.analysis.get("competencies") or []):
        imp = jd_c.get("importance", "preferred")
        w = config.IMPORTANCE_WEIGHT.get(imp, 1.0)
        match = an.get("match", "none")
        ev = an.get("evidence_type", "none")
        if match == "none":
            ev = "none"
        m = config.MATCH_FACTOR.get(match, 0.0)
        e = config.EVIDENCE_FACTOR[ctx.level].get(ev, 0.0)
        r = _recency_factor(an.get("last_used"), ctx.today) if m > 0 else 0.0
        contrib = w * m * e * r
        num += contrib
        den += w
        rows.append({"name": jd_c.get("name"), "importance": imp, "match": match, "evidence_type": ev,
                     "last_used": an.get("last_used"), "quote": an.get("quote"),
                     "factors": {"w": w, "m": m, "e": e, "r": r}, "value": round(contrib / w, 3) if w else 0})
    score = round(10 * num / den, 1) if den else 10.0
    raw_cut = ctx.jd.get("skill_cutoff")
    cutoff = float(raw_cut) if raw_cut not in (None, "") else config.SKILL_CUTOFF[ctx.level]
    return {"score": score, "cutoff": cutoff, "passed": score >= cutoff}, rows



# ---------- degree matching ----------

CS_FIELD = re.compile(
    r"\b(computer|computing|cse|cs|it|information (technology|science|systems)|software|ece|electronics|"
    r"electrical|e&c|e&tc|eee|telecom\w*|data science|artificial intelligence|ai|machine learning|"
    r"mathematics and computing|math(s|ematics)? (and|&) computing|bca|mca|cyber ?security)\b", re.I)
DEGREE_LEVEL = re.compile(
    r"\b(b\.? ?tech|b\.? ?e\b|b\.? ?sc|bs\b|bachelor|bca|m\.? ?tech|m\.? ?e\b|m\.? ?sc|ms\b|master|mca|"
    r"ph\.? ?d|doctor|dual degree|integrated)", re.I)
EQUIVALENT = re.compile(r"equivalent (work |practical |industry )?experience|or equivalent", re.I)


def degree_assessment(ctx: "Context", yoe: float) -> tuple[float, str | None]:
    """Credit 0-1 for the JD's degree requirement. Any bachelor's-or-higher in a CS-related field
    (CS, IT, ECE, BCA, MCA, M.Tech CSE, ...) is a full match. If the JD accepts 'equivalent work
    experience', enough relevant experience also counts as a full match."""
    edu = ctx.resume.get("education") or []
    for e in edu:
        text = f"{e.get('degree', '')} {e.get('branch', '')}"
        if DEGREE_LEVEL.search(text) and (CS_FIELD.search(text) or re.search(r"\b(bca|mca)\b", text, re.I)):
            return 1.0, f"{e.get('degree', '')} {e.get('branch') or ''}".strip()
    deg_text = (ctx.jd.get("degree") or {}).get("text", "")
    if EQUIVALENT.search(deg_text) and yoe >= config.EQUIVALENT_EXPERIENCE_YEARS[ctx.level]:
        return 1.0, f"Equivalent work experience: {yoe} relevant years"
    llm = {"yes": 1.0, "not_required": 1.0, "related": 0.75}.get(ctx.analysis.get("degree_match", "no"), 0.0)
    if llm == 0 and edu and any(DEGREE_LEVEL.search(f"{e.get('degree', '')}") for e in edu):
        llm = 0.25  # some bachelor's+, unrelated field
    return llm, None

# ---------- L1 ----------

def _check(rule_id, rule, credit, evidence=None, reason=None, hard=False):
    credit = round(_clamp(credit), 2)
    status = "met" if credit >= 1 else "partial" if credit > 0 else "missing"
    return {"rule_id": rule_id, "rule": rule, "credit": credit, "status": status, "passed": credit >= 1,
            "evidence": evidence, "reason": None if credit >= 1 else reason, "hard": hard}


def knockouts(ctx: Context, yoe: float, comp_rows: list[dict]) -> tuple[list[dict], dict, list[str]]:
    """Required-criteria gate: each Required item earns credit 0-1; coverage % is compared with the
    editable threshold. Only JD red flags are hard knockouts."""
    out, flags = [], []
    for i, c in enumerate(comp_rows):
        if c["importance"] != "required":
            continue
        credit = 0.0 if c["match"] == "none" or c["evidence_type"] == "none" else 1.0 if c["match"] == "exact" else 0.5
        out.append(_check(f"REQ-SKILL-{i + 1}", f"Required skill: {c['name']}", credit, c.get("quote"),
                          f"Missing Required: {c['name']}" if credit == 0 else f"Only a related skill for {c['name']}"))

    req_exp = [x for x in ctx.jd.get("experience_requirements") or [] if x.get("importance") == "required"]
    mins = [float(x["min_yoe"]) for x in req_exp if x.get("min_yoe") is not None]
    min_req = max(mins) if mins else None
    if min_req:
        credit = 1.0 if yoe >= min_req - 0.25 else yoe / min_req
        out.append(_check("REQ-YOE", f"At least {min_req:g} years of relevant experience", credit,
                          f"{yoe} relevant years computed from roles",
                          f"{yoe} relevant years vs {min_req:g} required"))

    pairs = _paired(ctx.jd.get("experience_requirements") or [], ctx.analysis.get("experience_requirements") or [])
    for i, (jd_x, an) in enumerate(pairs):
        if jd_x.get("importance") != "required":
            continue
        credit = {"yes": 1.0, "partial": 0.5}.get(an.get("met", "no"), 0.0)
        out.append(_check(f"REQ-EXP-{i + 1}", jd_x.get("text"), credit, an.get("quote"),
                          f"Not clearly shown: {jd_x.get('text')}"))

    deg = ctx.jd.get("degree")
    if deg and deg.get("importance") == "required":
        credit, ev = degree_assessment(ctx, yoe)
        out.append(_check("REQ-DEGREE", deg.get("text"), credit, ev, "Degree is not in a CS-related field the JD accepts"))

    certs = ctx.jd.get("certifications") or []
    met = ctx.analysis.get("certifications_met") or []
    for i, c in enumerate(certs):
        if c.get("importance") == "required":
            credit = 1.0 if i < len(met) and met[i] else 0.0
            out.append(_check(f"REQ-CERT-{i + 1}", c.get("text"), credit, None, f"Missing certification: {c.get('text')}"))

    soft = [k for k in out if not k["hard"]]
    coverage = round(100 * sum(k["credit"] for k in soft) / len(soft), 1) if soft else 100.0
    threshold = float(ctx.jd.get("required_threshold", config.REQUIRED_THRESHOLD))
    for k in soft:
        if not k["passed"]:
            flags.append(f"required_{k['status']}: {k['rule']}")

    for i, (flag, an) in enumerate(_paired(ctx.jd.get("red_flags") or [], ctx.analysis.get("red_flags_hit") or [])):
        hit = bool(an.get("hit"))
        out.append(_check(f"RF-{i + 1}", f"Red flag: {flag}", 0.0 if hit else 1.0, an.get("quote"),
                          f"Matches red flag: {flag}", hard=True))
    red_flag_hit = any(k["hard"] and not k["passed"] for k in out)
    gate = {"coverage": coverage, "threshold": threshold, "items": len(soft),
            "passed": coverage >= threshold and not red_flag_hit, "red_flag_hit": red_flag_hit}
    return out, gate, flags


# ---------- L3 ----------

def _yoe_band(ctx: Context, yoe: float) -> float:
    req = ctx.jd.get("min_yoe")
    Y = float(req) if req is not None else (0.0 if ctx.level == "entry" else 5.0)
    if yoe >= Y:
        if ctx.level == "entry" and yoe > Y + config.OVERQUALIFIED_MARGIN_YEARS:
            return 0.7
        return 1.0
    if yoe >= Y - 1:
        return 0.6
    return max(0.2, 0.6 * yoe / Y) if Y else 0.2


def _bullets(ctx: Context) -> list[str]:
    return [b for r in ctx.roles for b in (r.get("bullets") or [])]


def quantified_ratio(ctx: Context) -> float:
    bullets = _bullets(ctx)
    if not bullets:
        return 0.0
    return sum(1 for b in bullets if QUANTIFIED.search(b)) / len(bullets)


def dimensions(ctx: Context, yoe: float, gate: dict, comp_rows: list[dict], flags: list[str]) -> list[dict]:
    W = config.WEIGHTS[ctx.level]
    dims: dict[str, dict] = {}

    # D1 skills
    pref = [c for c in comp_rows if c["importance"] == "preferred"]
    pref_cov = (sum(1 for c in pref if c["match"] != "none") / len(pref)) if pref else 1.0
    d1 = 0.8 * (gate["score"] / 10) + 0.2 * pref_cov
    missing = [c["name"] for c in comp_rows if c["match"] == "none"]
    dims["D1"] = {"raw": d1, "evidence": [c["quote"] for c in comp_rows if c.get("quote")][:4],
                  "gaps": [f"Not found: {n}" for n in missing][:6]}

    # D2 experience relevance
    band = _yoe_band(ctx, yoe)
    domain = _clamp(float(ctx.analysis.get("domain_relevance", 0.5) or 0))
    prefs = [(j, a) for j, a in _paired(ctx.jd.get("experience_requirements") or [],
                                       ctx.analysis.get("experience_requirements") or [])
             if j.get("importance") == "preferred"]
    if prefs:
        frac = sum({"yes": 1, "partial": 0.5}.get(a.get("met"), 0) for _, a in prefs) / len(prefs)
        d2 = 0.4 * band + 0.3 * domain + 0.3 * frac
    else:
        d2 = 0.55 * band + 0.45 * domain
    d2_gaps = [f"Preferred experience not shown: {j.get('text')}" for j, a in prefs if a.get("met") == "no"]
    if band < 1:
        d2_gaps.insert(0, f"{yoe} relevant years against the JD's ask")
    dims["D2"] = {"raw": d2, "evidence": [f"{yoe} relevant years", f"domain relevance {domain:.2f}"], "gaps": d2_gaps}

    # D3 impact
    imp = _rubric(ctx, "impact")
    qr = quantified_ratio(ctx)
    d3 = 0.5 * imp["score"] + 0.5 * _clamp(qr / 0.5)
    gaps = list(imp["gaps"])
    if qr < 0.5:
        gaps.insert(0, f"Only {round(qr * 100)}% of work bullets have numbers; aim for at least half")
    dims["D3"] = {"raw": d3, "evidence": imp["evidence"], "gaps": gaps}

    for key, rub in (("D4", "ownership"), ("D5", "projects")):
        r = _rubric(ctx, rub)
        dims[key] = {"raw": r["score"], "evidence": r["evidence"], "gaps": r["gaps"]}

    # D6 education
    edu = ctx.resume.get("education") or []
    parts: list[tuple[float, float]] = []
    if ctx.jd.get("degree"):
        deg_val, _ = degree_assessment(ctx, yoe)
        deg_val = max(deg_val, 0.3 if edu else 0.0)
    else:
        deg_val = 1.0 if edu else 0.5
    dm = "yes" if deg_val >= 1 else "no"
    parts.append((0.6, deg_val))
    jd_certs = ctx.jd.get("certifications") or []
    if jd_certs:
        met = ctx.analysis.get("certifications_met") or []
        parts.append((0.2, sum(1 for i in range(len(jd_certs)) if i < len(met) and met[i]) / len(jd_certs)))
    if ctx.level == "entry":
        cg = next((e.get("cgpa") for e in edu if e.get("cgpa") is not None), None)
        cg_val = 0.6 if cg is None else (1.0 if cg >= 8.5 else 0.85 if cg >= 7.5 else 0.65 if cg >= 6.5 else 0.4)
        parts.append((0.2, cg_val))
    d6 = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
    bonus = 0.0
    if ctx.jd.get("college_preference") and any(e.get("is_renowned") for e in edu):
        bonus = config.RENOWNED_INSTITUTE_BONUS
    dims["D6"] = {"raw": d6, "bonus": bonus,
                  "evidence": [f"{e.get('degree', '')} {e.get('branch') or ''}, {e.get('institute', '')}".strip()
                               for e in edu][:2],
                  "gaps": [] if dm in ("yes", "not_required") else ["Degree is not an exact match for the JD"]}

    # D7 trajectory
    ft = [r for r in ctx.roles if r.get("employment_type") != "internship"]
    ivs = sorted(filter(None, (_role_interval(r, ctx.today) for r in ft)))
    gaps7: list[str] = []
    if len(ivs) < 2:
        d7 = 0.7
    else:
        tenures = [e - s + 1 for s, e in ivs]
        avg = sum(tenures) / len(tenures)
        d7 = 1.0 if avg >= 18 else 0.7 if avg >= 12 else 0.4
        if avg < 18:
            gaps7.append(f"Average tenure {avg:.0f} months")
        companies: dict[str, set] = {}
        for r in ft:
            companies.setdefault((r.get("company") or "").strip().lower(), set()).add((r.get("title") or "").lower())
        promos = sum(1 for t in companies.values() if len(t) > 1)
        d7 += min(0.3, 0.15 * promos)
        for (s1, e1), (s2, _) in zip(ivs, ivs[1:]):
            if s2 - e1 - 1 > 6:
                d7 -= 0.15
                flags.append(f"career_gap: {s2 - e1 - 1} months")
                gaps7.append(f"Unexplained gap of {s2 - e1 - 1} months (add a line if it was a break)")
    dims["D7"] = {"raw": _clamp(d7), "evidence": [], "gaps": gaps7}

    # D8 resume quality
    rq = _rubric(ctx, "resume_quality")
    limit = config.PAGE_LIMIT[ctx.level]
    pages = ctx.parsed.page_count
    page_val = 1.0 if pages <= limit else 0.6 if pages == limit + 1 else 0.3
    gaps8 = list(rq["gaps"])
    if pages > limit:
        gaps8.insert(0, f"{pages} pages; keep it to {limit} for this level")
    dims["D8"] = {"raw": 0.6 * rq["score"] + 0.4 * page_val, "evidence": rq["evidence"], "gaps": gaps8}

    out = []
    for key in ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"):
        d = dims[key]
        raw = round(_clamp(d["raw"]), 3)
        points = min(W[key], W[key] * raw + d.get("bonus", 0.0))
        out.append({"id": key, "name": config.DIMENSION_NAMES[key], "weight": W[key], "raw": raw,
                    "points": round(points, 1), "bonus": d.get("bonus", 0.0),
                    "evidence": [e for e in d["evidence"] if e][:4], "gaps": d["gaps"][:5]})
    return out


# ---------- L4 ----------

def _ngrams(text: str, n: int = 8) -> set:
    toks = re.findall(r"[a-z0-9+#]+", text.lower())
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def integrity(ctx: Context, yoe: float) -> tuple[list[dict], list[str]]:
    pens, flags = [], []
    if ctx.parsed.hidden_text:
        pens.append({"check": "hidden_text", "points": -10,
                     "detail": f"{len(ctx.parsed.hidden_text)} run(s) of white, tiny or off-page text",
                     "sample": ctx.parsed.hidden_text[:3]})
        flags.append("hidden_text")

    skills = ctx.resume.get("skills_section") or []
    if skills:
        body = " ".join(_bullets(ctx) + [p.get("description") or "" for p in ctx.resume.get("projects") or []]).lower()
        unbacked = [s for s in skills if s and s.lower() not in body]
        ratio = len(unbacked) / len(skills)
        if len(skills) > 40 or (len(skills) >= 20 and ratio > 0.7):
            pts = -5 if len(skills) > 40 else -3
            pens.append({"check": "keyword_stuffing", "points": pts,
                         "detail": f"{len(skills)} listed skills, {round(ratio * 100)}% never used in bullets or projects"})

    if ctx.jd_text:
        jd_ng = _ngrams(ctx.jd_text)
        if jd_ng:
            overlap = len(jd_ng & _ngrams(ctx.parsed.text)) / len(jd_ng)
            if overlap > 0.25:
                pens.append({"check": "jd_copy_paste", "points": -5,
                             "detail": f"{round(overlap * 100)}% of the JD's 8-word phrases appear verbatim"})

    conflicts = []
    ivs = []
    for r in ctx.roles:
        s, e = parse_ym(r.get("start"), ctx.today), parse_ym(r.get("end") or "present", ctx.today)
        if s and e and to_index(e) < to_index(s):
            conflicts.append(f"{r.get('company')}: end date before start date")
        elif s and e and r.get("employment_type") == "full_time":
            ivs.append((to_index(s), to_index(e), r.get("company")))
    ivs.sort()
    for (s1, e1, c1), (s2, e2, c2) in zip(ivs, ivs[1:]):
        if c1 != c2 and e1 - s2 >= 1:
            conflicts.append(f"Overlapping full-time roles: {c1} and {c2}")
    if conflicts:
        pens.append({"check": "timeline_conflict", "points": -3, "detail": "; ".join(conflicts[:3])})
        flags.append("timeline_conflict")

    if yoe < 3 and any(SENIOR_TITLE.search(r.get("title") or "") for r in ctx.roles
                       if r.get("employment_type") != "internship"):
        flags.append("title_inflation")
    return pens, flags


# ---------- L5 ----------

def band_for(score: float) -> tuple[str, str]:
    for lower, name, action in config.BANDS:
        if score >= lower:
            return name, action
    return config.BANDS[-1][1], config.BANDS[-1][2]


def compute(ctx: Context) -> Result:
    yoe = relevant_yoe(ctx)
    gate, comp_rows = skill_gate(ctx)
    kos, req_gate, flags = knockouts(ctx, yoe, comp_rows)
    dims = dimensions(ctx, yoe, gate, comp_rows, flags)
    pens, iflags = integrity(ctx, yoe)
    flags += iflags
    penalty = max(-config.MAX_INTEGRITY_PENALTY, sum(p["points"] for p in pens))
    raw = sum(d["points"] for d in dims) + penalty
    score = int(round(_clamp(raw, 0, 100)))
    band, action = band_for(score)
    rejected = not req_gate["passed"] or not gate["passed"]
    if rejected:
        if req_gate["red_flag_hit"]:
            why = "a red flag in the JD"
        elif not req_gate["passed"]:
            why = f"the Required criteria ({req_gate['coverage']:g}% met, needs {req_gate['threshold']:g}%)"
        else:
            why = "the technical skill cutoff"
        action = (f"It fails {why}, so it would likely be filtered out before anyone reads it. "
                  "Fix the top-ranked items first.")
    return Result(status="WOULD_BE_REJECTED" if rejected else "PASS", level=ctx.level, score=score, band=band,
                  band_action=action, yoe=yoe, skill_gate=gate, required_gate=req_gate, knockouts=kos, dimensions=dims, penalties=pens,
                  flags=flags, competencies=comp_rows, raw_score=raw)
