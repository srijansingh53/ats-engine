"""Runs L0-L5 and builds ranked, gain-estimated fixes for the candidate."""
from __future__ import annotations

import copy
from datetime import date

from .. import config
from ..parsing import ParsedDocument
from .scoring import Context, compute

MIN_TEXT_CHARS = 200
ENGINE_VERSION = "weights@v1"


KIND_ORDER = {"knockout": 0, "gate": 1}


def _rescore_with(ctx: Context, mutate):
    an = copy.deepcopy(ctx.analysis)
    mutate(an)
    return compute(Context(jd=ctx.jd, analysis=an, parsed=ctx.parsed, today=ctx.today, jd_text=ctx.jd_text))


def build_fixes(ctx: Context, result) -> list[dict]:
    fixes: list[dict] = []
    base = result.raw_score
    comps = ctx.analysis.get("competencies") or []
    gate_failed = not result.skill_gate["passed"]

    for i, row in enumerate(result.competencies):
        if i >= len(comps):
            break
        name, imp = row["name"], row["importance"]
        ev, match, rec = row["evidence_type"], row["match"], row["factors"]["r"]
        if ev == "experience_outcome" and match == "exact" and rec >= 1:
            continue

        def mutate(an, i=i):
            c = an["competencies"][i]
            c["match"] = "exact"
            c["evidence_type"] = "experience_outcome" if c.get("evidence_type") == "experience_outcome" else "experience"
            c["last_used"] = "present"

        new = _rescore_with(ctx, mutate)
        gain = new.raw_score - base
        gate_gain = new.skill_gate["score"] - result.skill_gate["score"]
        clears = imp == "required" and match == "none"
        if match == "none":
            action = (f"{name} ({imp}) is not on your resume. If you have used it, add a work or project bullet "
                      f"that names {name} and what you built with it. If you haven't, this is a real gap.")
        elif ev == "skills_only":
            action = f"{name} appears only in your skills list. Show it in a work bullet with what you built and the result."
        elif match == "adjacent":
            action = f"You show a related skill for {name}. If you have used {name} itself, name it explicitly."
        elif ev == "project" and ctx.level == "senior":
            action = f"{name} is shown only in projects. Add it to a work bullet if you used it on the job."
        elif rec < 1:
            action = (f"{name} was last shown in {row.get('last_used')}. If you use it in your current role, "
                      f"say so in a current bullet. Older skills count for less.")
        else:
            continue
        if gain < 0.5 and not clears and gate_gain < 0.3:
            continue
        kind = "knockout" if clears else "gate" if gate_failed and gate_gain >= 0.3 else "skill"
        fixes.append({"action": action, "est_gain": round(gain, 1), "kind": kind, "target": name,
                      "skill_gate_gain": round(gate_gain, 1)})

    # rubric dimensions
    for d in result.dimensions:
        if d["id"] in ("D1", "D2", "D7"):
            continue
        headroom = d["weight"] - d["points"]
        if headroom < 1:
            continue
        for g in d["gaps"][:2]:
            fixes.append({"action": g, "est_gain": round(min(headroom, d["weight"] * 0.25) / max(1, len(d["gaps"][:2])), 1),
                          "kind": "quality", "target": d["name"]})

    for p in result.penalties:
        msg = {
            "hidden_text": "Remove white, tiny or off-page text. ATS tools flag it as manipulation.",
            "keyword_stuffing": "Cut the skills list to skills your bullets and projects actually back up.",
            "jd_copy_paste": "Rewrite the sentences copied from the JD in your own words, with your own results.",
            "timeline_conflict": "Fix the conflicting dates: " + p.get("detail", ""),
        }.get(p["check"])
        if msg:
            fixes.append({"action": msg, "est_gain": float(-p["points"]), "kind": "integrity", "target": p["check"]})

    fixes.sort(key=lambda f: (KIND_ORDER.get(f["kind"], 2), -f.get("skill_gate_gain", 0) if f["kind"] == "gate" else 0,
                              -f["est_gain"]))
    for rank, f in enumerate(fixes, 1):
        f["rank"] = rank
    return fixes[:12]


def score_resume(jd: dict, analysis: dict, parsed: ParsedDocument, jd_text: str = "",
                 today: date | None = None) -> dict:
    today = today or date.today()
    level = jd.get("level") if jd.get("level") in config.LEVELS else "entry"
    if parsed.char_count < MIN_TEXT_CHARS:
        return {"status": "NEEDS_REVIEW", "level": level, "score": None, "band": None,
                "message": "Too little text could be read from the resume. It may be a scanned image; "
                           "export it as a text-based PDF or DOCX and try again.",
                "engine_version": ENGINE_VERSION}
    ctx = Context(jd=jd, analysis=analysis, parsed=parsed, today=today, jd_text=jd_text)
    result = compute(ctx)
    out = result.to_dict()
    out.pop("raw_score", None)
    out["fixes"] = build_fixes(ctx, result)
    out["page_count"] = parsed.page_count
    out["engine_version"] = f"{ENGINE_VERSION}, model@{config.ANTHROPIC_MODEL}"
    out["disclaimer"] = ("This score approximates typical ATS screening for software roles. "
                         "It is not any specific employer's system.")
    return out
