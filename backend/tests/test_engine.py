import io
from datetime import date

from ats import config
from ats.engine.dates import union_months
from ats.engine.pipeline import score_resume
from ats.engine.scoring import Context, relevant_yoe, skill_gate
from ats.parsing import ParsedDocument, parse_pdf

TODAY = date(2026, 11, 4)
DOC = ParsedDocument(text="x" * 500, page_count=1)


def ctx(jd, analysis, doc=DOC, jd_text=""):
    return Context(jd=jd, analysis=analysis, parsed=doc, today=TODAY, jd_text=jd_text)


def test_weights_sum_to_100():
    for level, w in config.WEIGHTS.items():
        assert sum(w.values()) == 100, level


def test_union_months_merges_overlap():
    assert union_months([(0, 11), (6, 17)]) == 18
    assert union_months([(0, 0), (2, 2)]) == 2


def test_yoe_internship_multiplier(jd, analysis):
    assert relevant_yoe(ctx(jd, analysis)) == 7.4  # senior: internship x0
    jd["level"] = "entry"
    assert relevant_yoe(ctx(jd, analysis)) == 7.7  # entry: +6 months x0.5


def test_skill_gate_formula_and_recency(jd, analysis):
    gate, rows = skill_gate(ctx(jd, analysis))
    # Python 2*1*.8*1 + Flask 2*1*1*.4 (65 months ago) + AWS 1*1*.8*1 + React 1*1*.6*.4 = 3.44 / 6
    assert gate["score"] == 5.7
    assert gate["passed"] is False
    analysis["competencies"][1]["last_used"] = "present"
    gate, _ = skill_gate(ctx(jd, analysis))
    assert gate["score"] == 7.7 and gate["passed"]


def test_pass_case_scores_and_bands(jd, analysis):
    analysis["competencies"][1]["last_used"] = "present"
    out = score_resume(jd, analysis, DOC, today=TODAY)
    assert out["status"] == "PASS"
    assert 0 <= out["score"] <= 100
    assert {d["id"] for d in out["dimensions"]} == set(config.WEIGHTS["senior"])
    d6 = next(d for d in out["dimensions"] if d["id"] == "D6")
    assert d6["bonus"] == config.RENOWNED_INSTITUTE_BONUS
    assert d6["points"] <= d6["weight"]


def test_one_missing_required_is_flagged_not_rejected(jd, analysis):
    # 5 required items (Python, Flask group, YoE, exp line, degree); missing 1 -> 80% >= 70%
    analysis["competencies"][1]["last_used"] = "present"
    analysis["competencies"][0].update(match="none", evidence_type="none", quote=None, last_used=None)
    jd["skill_cutoff"] = 0
    out = score_resume(jd, analysis, DOC, today=TODAY)
    assert out["required_gate"]["coverage"] == 80.0
    assert out["required_gate"]["passed"] and out["status"] == "PASS"
    assert any(f.startswith("required_missing") for f in out["flags"])
    fix = next(f for f in out["fixes"] if f["target"] == "Python")
    assert fix["kind"] == "required"


def test_below_required_threshold_rejects_with_knockout_fix_first(jd, analysis):
    for i in (0, 1):
        analysis["competencies"][i].update(match="none", evidence_type="none", quote=None, last_used=None)
    out = score_resume(jd, analysis, DOC, today=TODAY)
    assert out["required_gate"]["coverage"] == 60.0
    assert out["status"] == "WOULD_BE_REJECTED"
    assert out["fixes"][0]["kind"] == "knockout"


def test_required_threshold_is_editable(jd, analysis):
    for i in (0, 1):
        analysis["competencies"][i].update(match="none", evidence_type="none", quote=None, last_used=None)
    jd["required_threshold"] = 50
    jd["skill_cutoff"] = 0
    assert score_resume(jd, analysis, DOC, today=TODAY)["status"] == "PASS"


def test_renowned_bonus_only_when_jd_prefers(jd, analysis):
    jd["college_preference"] = None
    out = score_resume(jd, analysis, DOC, today=TODAY)
    d6 = next(d for d in out["dimensions"] if d["id"] == "D6")
    assert d6["bonus"] == 0


def test_yoe_partial_credit(jd, analysis):
    jd["experience_requirements"][0]["min_yoe"] = 10
    out = score_resume(jd, analysis, DOC, today=TODAY)
    yoe = next(k for k in out["knockouts"] if k["rule_id"] == "REQ-YOE")
    assert yoe["status"] == "partial" and yoe["credit"] == 0.74


def test_red_flag_knockout(jd, analysis):
    jd["red_flags"] = ["No backend experience"]
    analysis["red_flags_hit"] = [{"flag": "No backend experience", "hit": True, "quote": "x"}]
    out = score_resume(jd, analysis, DOC, today=TODAY)
    assert out["status"] == "WOULD_BE_REJECTED"


def test_integrity_penalties_capped(jd, analysis):
    analysis["resume"]["skills_section"] = [f"skill{i}" for i in range(45)]
    analysis["resume"]["roles"].append({"company": "Other", "title": "Engineer", "start": "2022-01", "end": "2023-01",
                                        "employment_type": "full_time", "is_software_role": True, "bullets": []})
    doc = ParsedDocument(text="y" * 500, page_count=1, hidden_text=["python kafka aws"])
    out = score_resume(jd, analysis, doc, today=TODAY)
    checks = {p["check"] for p in out["penalties"]}
    assert {"hidden_text", "keyword_stuffing", "timeline_conflict"} <= checks
    assert "hidden_text" in out["flags"]


def test_jd_copy_detected(jd, analysis):
    jd_text = "We are looking for a backend engineer who can design scalable distributed systems for millions of users daily"
    doc = ParsedDocument(text="Summary: " + jd_text + " and more.", page_count=1)
    doc.text += " filler" * 100
    out = score_resume(jd, analysis, doc, jd_text=jd_text, today=TODAY)
    assert any(p["check"] == "jd_copy_paste" for p in out["penalties"])


def test_needs_review_for_empty_text(jd):
    out = score_resume(jd, {}, ParsedDocument(text="  ", page_count=1), today=TODAY)
    assert out["status"] == "NEEDS_REVIEW"


def test_deterministic(jd, analysis):
    a = score_resume(jd, analysis, DOC, today=TODAY)
    b = score_resume(jd, analysis, DOC, today=TODAY)
    assert a == b


def test_page_limit_gap(jd, analysis):
    out = score_resume(jd, analysis, ParsedDocument(text="x" * 500, page_count=3), today=TODAY)
    d8 = next(d for d in out["dimensions"] if d["id"] == "D8")
    assert any("pages" in g for g in d8["gaps"])


def test_pdf_hidden_text_detection():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 750, "Visible resume text for a backend engineer")
    c.setFillColorRGB(1, 1, 1)
    c.drawString(72, 700, "kubernetes terraform golang")
    c.save()
    doc = parse_pdf(buf.getvalue())
    assert doc.page_count == 1
    assert any("kubernetes" in h for h in doc.hidden_text)
    assert "Visible resume text" in doc.text


import pytest


@pytest.mark.parametrize("degree,branch,expected", [
    ("B.Tech", "Information Technology", 1.0),
    ("B.E.", "Electronics and Communication", 1.0),
    ("BCA", "", 1.0),
    ("MCA", "", 1.0),
    ("M.Tech", "CSE", 1.0),
    ("B.Sc", "Computer Science", 1.0),
    ("B.Tech", "Mechanical Engineering", 0.25),
    ("BA", "History", 0.0),
])
def test_degree_cs_related_fields(jd, analysis, degree, branch, expected):
    jd["degree"] = {"text": "Bachelor's+ in Computer Science or related field", "importance": "required"}
    analysis["degree_match"] = "no"  # rule-based matching must not depend on the LLM
    analysis["resume"]["education"] = [{"institute": "X", "degree": degree, "branch": branch, "is_renowned": False}]
    out = score_resume(jd, analysis, DOC, today=TODAY)
    ko = next(k for k in out["knockouts"] if k["rule_id"] == "REQ-DEGREE")
    assert ko["credit"] == expected


def test_degree_equivalent_experience(jd, analysis):
    jd["degree"] = {"text": "Bachelor's+ in CS or related field, or equivalent work experience", "importance": "required"}
    analysis["degree_match"] = "no"
    analysis["resume"]["education"] = []
    out = score_resume(jd, analysis, DOC, today=TODAY)  # 7.4 relevant years >= 5 (senior)
    ko = next(k for k in out["knockouts"] if k["rule_id"] == "REQ-DEGREE")
    assert ko["credit"] == 1.0 and "Equivalent work experience" in ko["evidence"]
    jd["degree"]["text"] = "Bachelor's in CS required"
    out = score_resume(jd, analysis, DOC, today=TODAY)
    assert next(k for k in out["knockouts"] if k["rule_id"] == "REQ-DEGREE")["credit"] == 0.0
