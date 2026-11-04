"""Scoring configuration. Mirrors the PRD: weights per level, gate cutoffs, factors."""
import os

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "5"))

LEVELS = ("entry", "senior")

# L3 weights (each level sums to 100)
WEIGHTS = {
    "entry": {"D1": 30, "D2": 10, "D3": 10, "D4": 5, "D5": 20, "D6": 15, "D7": 5, "D8": 5},
    "senior": {"D1": 25, "D2": 20, "D3": 15, "D4": 15, "D5": 5, "D6": 5, "D7": 10, "D8": 5},
}

DIMENSION_NAMES = {
    "D1": "Skills match",
    "D2": "Experience relevance",
    "D3": "Impact",
    "D4": "Ownership and seniority",
    "D5": "Projects and proof of work",
    "D6": "Education and certs",
    "D7": "Career trajectory",
    "D8": "Resume quality",
}

# L2 skill gate
SKILL_CUTOFF = {"entry": 6.0, "senior": 7.0}
IMPORTANCE_WEIGHT = {"required": 2.0, "preferred": 1.0}
MATCH_FACTOR = {"exact": 1.0, "adjacent": 0.5, "none": 0.0}
EVIDENCE_FACTOR = {
    "entry": {"experience_outcome": 1.0, "experience": 0.8, "project": 0.8, "skills_only": 0.3, "none": 0.0},
    "senior": {"experience_outcome": 1.0, "experience": 0.8, "project": 0.6, "skills_only": 0.3, "none": 0.0},
}
# recency: months since last use -> factor
RECENCY_STEPS = [(24, 1.0), (60, 0.7)]
RECENCY_OLD = 0.4

INTERNSHIP_YOE_MULTIPLIER = {"entry": 0.5, "senior": 0.0}
PAGE_LIMIT = {"entry": 1, "senior": 2}
OVERQUALIFIED_MARGIN_YEARS = 4  # entry only

# Institute bonus: only when JD marks college preference as preferred
RENOWNED_INSTITUTE_BONUS = 3

# L4
MAX_INTEGRITY_PENALTY = 15

# L5 bands (lower bound inclusive)
BANDS = [
    (80, "Strong", "Likely to clear screening. Apply as is"),
    (65, "Good", "Competitive. Apply the top 2-3 fixes"),
    (50, "Borderline", "At risk. Fix the gaps before applying"),
    (0, "Weak", "Likely filtered out. Major gaps against this JD"),
]
