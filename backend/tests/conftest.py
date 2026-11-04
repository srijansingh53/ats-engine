import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

JD = {
    "title": "Backend Engineer",
    "level": "senior",
    "min_yoe": 5,
    "competencies": [
        {"name": "Python", "alternatives": ["Python"], "importance": "required"},
        {"name": "FastAPI or Flask or Django", "alternatives": ["FastAPI", "Flask", "Django"], "importance": "required"},
        {"name": "AWS", "alternatives": ["AWS"], "importance": "preferred"},
        {"name": "React.js", "alternatives": ["React"], "importance": "preferred"},
    ],
    "experience_requirements": [
        {"text": "5+ years as a backend engineer", "min_yoe": 5, "importance": "required"},
        {"text": "Startup experience", "min_yoe": None, "importance": "preferred"},
    ],
    "degree": {"text": "B.Tech in CS or related", "importance": "required"},
    "college_preference": {"text": "Tier 1 university is preferred", "importance": "preferred"},
    "certifications": [],
    "red_flags": [],
    "location": None,
}

RESUME = {
    "roles": [
        {"company": "Acme", "title": "SDE-1", "start": "2019-07", "end": "2021-06", "employment_type": "full_time",
         "is_software_role": True, "bullets": ["Built Flask APIs serving 2M users", "Wrote Python ETL jobs"]},
        {"company": "Acme", "title": "SDE-2", "start": "2021-07", "end": "present", "employment_type": "full_time",
         "is_software_role": True,
         "bullets": ["Cut p95 latency from 800ms to 120ms", "Led a team of 4 engineers on the Kafka migration",
                     "Designed the billing service on AWS"]},
        {"company": "Startup", "title": "Intern", "start": "2019-01", "end": "2019-06", "employment_type": "internship",
         "is_software_role": True, "bullets": ["Built a React dashboard"]},
    ],
    "projects": [{"name": "OSS", "description": "Contributor to an open-source Flask plugin"}],
    "skills_section": ["Python", "Flask", "AWS", "React", "Kafka"],
    "education": [{"institute": "IIIT Jabalpur", "degree": "B.Tech", "branch": "CSE", "end_year": 2019,
                   "cgpa": 8.1, "is_renowned": True}],
    "certifications": [],
    "achievements": [],
}

ANALYSIS = {
    "resume": RESUME,
    "competencies": [
        {"name": "Python", "match": "exact", "evidence_type": "experience", "last_used": "present", "quote": "Wrote Python ETL jobs"},
        {"name": "FastAPI or Flask or Django", "match": "exact", "evidence_type": "experience_outcome",
         "last_used": "2021-06", "quote": "Built Flask APIs serving 2M users"},
        {"name": "AWS", "match": "exact", "evidence_type": "experience", "last_used": "present",
         "quote": "Designed the billing service on AWS"},
        {"name": "React.js", "match": "exact", "evidence_type": "project", "last_used": "2019-06", "quote": "Built a React dashboard"},
    ],
    "experience_requirements": [
        {"text": "5+ years as a backend engineer", "met": "yes", "quote": None},
        {"text": "Startup experience", "met": "partial", "quote": "Startup intern"},
    ],
    "degree_match": "yes",
    "certifications_met": [],
    "red_flags_hit": [],
    "domain_relevance": 0.8,
    "rubrics": {
        "impact": {"score": 0.7, "evidence": ["Cut p95 latency from 800ms to 120ms"], "gaps": ["Add scale numbers to the billing service bullet"]},
        "ownership": {"score": 0.7, "evidence": ["Led a team of 4 engineers"], "gaps": ["Show a design decision you owned"]},
        "projects": {"score": 0.5, "evidence": ["Contributor to an open-source Flask plugin"], "gaps": []},
        "resume_quality": {"score": 0.8, "evidence": [], "gaps": []},
    },
}

RESUME_TEXT = ("Jane Doe\nBackend engineer\n" + "Built Flask APIs serving 2M users. Wrote Python ETL jobs. " * 10)


class FakeLLM:
    def __init__(self, jd=None, analysis=None):
        self.jd = jd or JD
        self.analysis = analysis or ANALYSIS
        self.calls = 0

    def extract_jd(self, jd_text):
        self.calls += 1
        return copy.deepcopy(self.jd)

    def analyze(self, resume_text, jd):
        self.calls += 1
        return copy.deepcopy(self.analysis)


@pytest.fixture
def jd():
    return copy.deepcopy(JD)


@pytest.fixture
def analysis():
    return copy.deepcopy(ANALYSIS)
