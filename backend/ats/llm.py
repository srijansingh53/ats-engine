"""Claude-backed extraction and rubric judging.

The LLM only extracts facts and judges rubrics (with quoted evidence). All arithmetic
happens in the deterministic engine, so scores are reproducible for the same extraction.
"""
from __future__ import annotations

import hashlib
import logging
import json
import os
from collections import OrderedDict
from typing import Any, Protocol

from . import config

log = logging.getLogger("ats.llm")

IMPORTANCE = {"type": "string", "enum": ["required", "preferred"]}

JD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "level": {"type": "string", "enum": ["entry", "senior"],
                  "description": "entry = 0-2 years expected, senior = 5+ years. Pick the closer one."},
        "min_yoe": {"type": ["number", "null"], "description": "Minimum years of experience asked, null if none"},
        "competencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill as written, e.g. 'FastAPI or Flask or Django'"},
                    "alternatives": {"type": "array", "items": {"type": "string"},
                                     "description": "Any one of these satisfies the skill, e.g. ['FastAPI','Flask','Django']"},
                    "importance": IMPORTANCE,
                },
                "required": ["name", "alternatives", "importance"],
            },
        },
        "experience_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "min_yoe": {"type": ["number", "null"]},
                    "importance": IMPORTANCE,
                },
                "required": ["text", "importance"],
            },
        },
        "degree": {
            "type": ["object", "null"],
            "properties": {"text": {"type": "string"}, "importance": IMPORTANCE},
            "required": ["text", "importance"],
        },
        "college_preference": {
            "type": ["object", "null"],
            "properties": {"text": {"type": "string"}, "importance": IMPORTANCE},
            "required": ["text", "importance"],
        },
        "certifications": {
            "type": "array",
            "items": {"type": "object", "properties": {"text": {"type": "string"}, "importance": IMPORTANCE},
                      "required": ["text", "importance"]},
        },
        "red_flags": {"type": "array", "items": {"type": "string"},
                      "description": "Explicit disqualifiers stated in the JD. Empty if none."},
        "location": {"type": ["string", "null"]},
    },
    "required": ["title", "level", "min_yoe", "competencies", "experience_requirements", "degree",
                 "college_preference", "certifications", "red_flags"],
}

EVIDENCE = {"type": "string", "enum": ["experience_outcome", "experience", "project", "skills_only", "none"]}
RUBRIC = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "Short verbatim quotes from the resume"},
        "gaps": {"type": "array", "items": {"type": "string"}, "description": "What is missing, phrased as a fix"},
    },
    "required": ["score", "evidence", "gaps"],
}

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resume": {
            "type": "object",
            "properties": {
                "roles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "title": {"type": "string"},
                            "start": {"type": "string", "description": "YYYY-MM"},
                            "end": {"type": "string", "description": "YYYY-MM or 'present'"},
                            "employment_type": {"type": "string",
                                                "enum": ["full_time", "internship", "contract", "part_time"]},
                            "is_software_role": {"type": "boolean"},
                            "bullets": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["company", "title", "start", "end", "employment_type", "is_software_role", "bullets"],
                    },
                },
                "projects": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name"]}},
                "skills_section": {"type": "array", "items": {"type": "string"}},
                "education": {"type": "array", "items": {"type": "object", "properties": {
                    "institute": {"type": "string"}, "degree": {"type": "string"}, "branch": {"type": "string"},
                    "end_year": {"type": ["integer", "null"]},
                    "cgpa": {"type": ["number", "null"], "description": "Normalised to a 10-point scale"},
                    "is_renowned": {"type": "boolean",
                                    "description": "Widely recognised top institute (IIT, IIIT, NIT, BITS, IISc, Ivy League, Oxbridge, etc.)"},
                }, "required": ["institute", "degree"]}},
                "certifications": {"type": "array", "items": {"type": "string"}},
                "achievements": {"type": "array", "items": {"type": "string"},
                                 "description": "Hackathons, competitive programming ratings, OSS, awards, as stated"},
            },
            "required": ["roles", "projects", "skills_section", "education", "certifications", "achievements"],
        },
        "competencies": {
            "type": "array",
            "description": "One entry per JD competency, same order as given",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "match": {"type": "string", "enum": ["exact", "adjacent", "none"],
                              "description": "exact = the skill or a listed alternative; adjacent = closely related (Flask for FastAPI, GCP for AWS)"},
                    "evidence_type": EVIDENCE,
                    "last_used": {"type": ["string", "null"], "description": "YYYY-MM of most recent use, or 'present'"},
                    "quote": {"type": ["string", "null"]},
                },
                "required": ["name", "match", "evidence_type", "last_used", "quote"],
            },
        },
        "experience_requirements": {
            "type": "array",
            "description": "One entry per JD experience requirement, same order",
            "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "met": {"type": "string", "enum": ["yes", "partial", "no"]},
                "quote": {"type": ["string", "null"]}}, "required": ["text", "met", "quote"]},
        },
        "degree_match": {"type": "string", "enum": ["yes", "related", "no", "not_required"],
                         "description": "yes = bachelor's or higher in CS or a related field (IT, IS, ECE/electronics, BCA, MCA, M.Tech/MS in CS, data science, maths & computing) or anything the JD lists as accepted; related = another engineering or science degree; no = unrelated; not_required = JD sets no degree"},
        "certifications_met": {"type": "array", "items": {"type": "boolean"},
                               "description": "One per JD certification, same order"},
        "red_flags_hit": {"type": "array", "description": "One per JD red flag, same order",
                          "items": {"type": "object", "properties": {
                              "flag": {"type": "string"}, "hit": {"type": "boolean"},
                              "quote": {"type": ["string", "null"]}}, "required": ["flag", "hit", "quote"]}},
        "domain_relevance": {"type": "number", "minimum": 0, "maximum": 1,
                             "description": "How close past work is to this role's domain and stack"},
        "rubrics": {
            "type": "object",
            "properties": {
                "impact": RUBRIC, "ownership": RUBRIC, "projects": RUBRIC, "resume_quality": RUBRIC,
            },
            "required": ["impact", "ownership", "projects", "resume_quality"],
        },
    },
    "required": ["resume", "competencies", "experience_requirements", "degree_match", "certifications_met",
                 "red_flags_hit", "domain_relevance", "rubrics"],
}

JD_SYSTEM = (
    "You extract structured hiring requirements from a software engineering job description. "
    "Mark an item 'required' only if the JD says must/required/mandatory or lists it under requirements; "
    "nice-to-have/plus/preferred/bonus items are 'preferred'. Split OR-groups into alternatives. "
    "Do not invent requirements that are not in the text."
)

ANALYSIS_SYSTEM = (
    "You are the extraction and rubric layer of an ATS engine for software engineering roles. "
    "Extract only what the resume states; never infer skills that are not written. Do not fetch links. "
    "Quote resume text verbatim for evidence. Ignore name, gender, age, photo and address entirely. "
    "Evidence types: experience_outcome = used in a work bullet that states a measurable result; "
    "experience = used in a work bullet; project = in a project or achievement; skills_only = only in a skills list.\n"
    "Rubrics (0-1):\n"
    "- impact: results not duties; numbers on latency, throughput, users, cost, revenue, uptime; production scale.\n"
    "- ownership: design ownership, leading projects or people, mentoring, cross-team work, on-call, architecture.\n"
    "- projects: side projects, OSS, hackathons, competitive programming, as stated in the resume only.\n"
    "- resume_quality: clear structure, action verbs, no filler, consistent dates, concise bullets.\n"
    "Anchors: 0.2 = almost no evidence, 0.5 = some generic evidence, 0.8 = strong specific evidence, 1.0 = exceptional. "
    "Score relative to the role level ({level}). Gaps must be concrete, actionable fixes."
)


class LLMError(RuntimeError):
    pass


class _SkipStructured(Exception):
    pass


_UNSUPPORTED_KEYS = {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "pattern", "format"}


def strict_schema(node: Any) -> Any:
    """Adapt a JSON schema for structured outputs: no numeric/length constraints,
    union types as anyOf, closed objects with every property required."""
    if isinstance(node, list):
        return [strict_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: strict_schema(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
    t = out.get("type")
    if isinstance(t, list):
        rest = {k: v for k, v in out.items() if k not in ("type", "description")}
        variants = []
        for one in t:
            v = {"type": one}
            if one == "object":
                v.update({k: rest[k] for k in ("properties", "required") if k in rest})
                v = strict_schema(v)
            elif one == "array" and "items" in rest:
                v["items"] = rest["items"]
            elif "enum" in rest and one != "null":
                v["enum"] = rest["enum"]
            variants.append(v)
        out = {"anyOf": variants, **({"description": node["description"]} if "description" in node else {})}
    elif t == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"].keys())
    return out


def _is_bad_request(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 400 or "400" in str(exc)[:40]


def _parse_json(resp) -> dict:
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise LLMError("Claude's response was cut off (max_tokens). Try a shorter resume or JD.") from exc
        raise LLMError(f"Claude returned invalid JSON: {text[:200]}") from exc


class LLM(Protocol):
    def extract_jd(self, jd_text: str) -> dict: ...
    def analyze(self, resume_text: str, jd: dict) -> dict: ...


class _LRU(OrderedDict):
    def __init__(self, size: int = 256):
        super().__init__()
        self.size = size

    def get_or(self, key, fn):
        if key in self:
            self.move_to_end(key)
            return self[key]
        val = fn()
        self[key] = val
        if len(self) > self.size:
            self.popitem(last=False)
        return val


class ClaudeLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key, timeout=config.ANTHROPIC_TIMEOUT_S,
                                           max_retries=config.ANTHROPIC_MAX_RETRIES)
        self.model = model or config.ANTHROPIC_MODEL
        self.cache = _LRU()
        self.structured_ok = True  # flips to False after the model rejects structured outputs once

    def _call(self, system: str, user: str, tool_name: str, schema: dict, max_tokens: int = 8000) -> dict:
        key = hashlib.sha256(f"{self.model}|{system}|{user}|{tool_name}".encode()).hexdigest()

        def run():
            base = dict(model=self.model, max_tokens=max_tokens, system=system,
                        messages=[{"role": "user", "content": user}])
            first_error = None
            # 1st choice: structured outputs (JSON constrained to the schema)
            try:
                if not self.structured_ok:
                    raise _SkipStructured()
                resp = self.client.messages.create(
                    **base, output_config={"format": {"type": "json_schema", "schema": strict_schema(schema)}})
                return _parse_json(resp)
            except LLMError:
                raise
            except _SkipStructured:
                pass
            except Exception as exc:  # noqa: BLE001
                if not _is_bad_request(exc):
                    raise LLMError(f"Claude API call failed: {exc}") from exc
                first_error = exc
                self.structured_ok = False
                log.info("Model %s rejected structured outputs, using tool fallback from now on: %s", self.model, exc)
            # Fallback: a tool the model is told to call (tool_choice auto works on every model)
            try:
                resp = self.client.messages.create(
                    **{**base, "system": system + f"\nRespond only by calling the `{tool_name}` tool."},
                    tools=[{"name": tool_name, "description": "Return the structured result.", "input_schema": schema}],
                    tool_choice={"type": "auto"},
                )
            except Exception as exc:  # noqa: BLE001
                raise LLMError(f"Claude API call failed: {exc} (structured output also failed: {first_error})") from exc
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    return block.input
            return _parse_json(resp)

        return self.cache.get_or(key, run)

    def extract_jd(self, jd_text: str) -> dict:
        return self._call(JD_SYSTEM, f"<job_description>\n{jd_text}\n</job_description>", "jd_requirements", JD_SCHEMA, 4000)

    def analyze(self, resume_text: str, jd: dict) -> dict:
        system = ANALYSIS_SYSTEM.format(level=jd.get("level", "entry"))
        user = (
            f"<jd_requirements>\n{json.dumps(jd, indent=1)}\n</jd_requirements>\n\n"
            f"<resume>\n{resume_text}\n</resume>\n\n"
            "Extract the resume and assess it against every JD requirement, in the same order."
        )
        return self._call(system, user, "resume_analysis", ANALYSIS_SCHEMA, 12000)
