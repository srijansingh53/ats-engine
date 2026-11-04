# ATS Engine

This tool scores a resume against a software engineering job description (entry or senior roles) out of 100. It explains every point and returns ranked, gain-estimated fixes. It is candidate-facing: it tells you whether a typical ATS would filter you out and what to change first.

**Stack:** Flask (Python 3.13) + React 18 (Vite), with Claude for extraction and rubric judging. Everything ships as one Docker image.

## How scoring works

| Layer | What it does | Outcome |
| --- | --- | --- |
| L0 Parse | PDF, DOCX or TXT to text. Detects white, tiny or off-page text and counts pages | `NEEDS_REVIEW` if unreadable |
| L1 Knockouts | Required skills, minimum YoE, required experience, degree, certs and JD red flags | `WOULD_BE_REJECTED` |
| L2 Skill gate | `10 × Σ w·m·e·r / Σ w` (importance × match × evidence × recency) vs the cutoff (6 for entry, 7 for senior) | `WOULD_BE_REJECTED` |
| L3 Fit | 8 dimensions × level weights (table below) | 0–100 |
| L4 Integrity | Hidden text −10, keyword stuffing −3/−5, JD copy-paste −5, timeline conflicts −3. Total capped at −15 | Penalty |
| L5 Band | Strong ≥ 80 · Good 65–79 · Borderline 50–64 · Weak < 50, plus ranked fixes | Report |

| Dimension | Entry | Senior |
| --- | --- | --- |
| D1 Skills match | 30 | 25 |
| D2 Experience relevance | 10 | 20 |
| D3 Impact | 10 | 15 |
| D4 Ownership and seniority | 5 | 15 |
| D5 Projects and proof of work | 20 | 5 |
| D6 Education and certs | 15 | 5 |
| D7 Career trajectory | 5 | 10 |
| D8 Resume quality | 5 | 5 |

Design rules:

- **Claude extracts, Python scores.** Claude turns the JD and resume into structured JSON and judges four rubrics (impact, ownership, projects, resume quality), quoting resume text as evidence. All arithmetic lives in `backend/ats/engine/`, so the same extraction always gives the same score. LLM calls are cached by input hash, so re-scoring the same resume and JD is stable.
- **Only what the resume says.** Links (GitHub, LeetCode) are never fetched.
- **Every company counts as an IT company.** There is no company-type classification.
- **No base score for institute tier.** A renowned college adds up to +3 in D6 only when the JD marks a college as Preferred.
- **PII is ignored.** Name, gender, age, photo and address are never inputs to scoring.
- **Fixes are honest.** Each fix's gain comes from rescoring with that gap closed. Fixes never suggest adding skills you don't have.

All weights, cutoffs and factors live in [`backend/ats/config.py`](backend/ats/config.py).

## Run locally

You need Python 3.11+, Node 20+ and an [Anthropic API key](https://console.anthropic.com).

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env       # then put your key in .env
python wsgi.py                      # API on http://localhost:5001

# frontend (second terminal)
cd frontend
npm install
npm run dev                         # UI on http://localhost:5173 (proxies /api to :5001)
```

Tests (no API key needed, since the LLM is faked):

```bash
cd backend && python -m pytest -q
```

## Run with Docker

```bash
docker build -t ats-engine .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... ats-engine
# open http://localhost:8000
```

## Deploy

CI (`.github/workflows/ci.yml`) runs the backend tests and the frontend build on every push and PR. On every push to `main` it also builds the image and publishes it to `ghcr.io/<owner>/ats-engine:latest`.

Any container host works. Set `ANTHROPIC_API_KEY` as a secret there.

- **Render:** New → Web Service → connect this repo. Render detects the Dockerfile. Add the `ANTHROPIC_API_KEY` env var. Render sets `PORT` itself.
- **Fly.io:** `fly launch` (it uses the Dockerfile), then `fly secrets set ANTHROPIC_API_KEY=...` and `fly deploy`.
- **Railway:** New Project → Deploy from GitHub repo → add `ANTHROPIC_API_KEY`.

GitHub Pages can't host this app on its own, because it only serves static files and the scoring API needs a server.

## API

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | none | `{ok, llm_configured, model}` |
| POST | `/api/jd/extract` | `{jd_text}` | `{jd}`: structured requirements (editable) |
| POST | `/api/score` | multipart: `resume` file, plus `jd` (JSON) or `jd_text`, optional `level` | Full report: status, score, band, skill gate, knockouts, dimensions, penalties, flags, fixes |

## Project layout

```
backend/
  ats/__init__.py        Flask app factory, routes, SPA serving
  ats/config.py          weights, cutoffs, factors
  ats/parsing.py         L0: PDF/DOCX/TXT parsing, hidden-text detection
  ats/llm.py             Claude extraction + rubric schemas
  ats/engine/scoring.py  L1–L5 deterministic layers
  ats/engine/pipeline.py orchestration + gain-estimated fixes
  tests/                 pytest (fake LLM)
frontend/
  src/App.jsx            input flow
  src/JDEditor.jsx       Required / Preferred editor, cutoff slider
  src/Results.jsx        score, gate, fixes, knockouts, breakdown
Dockerfile               multi-stage: build React, serve with gunicorn
```

The score approximates typical ATS screening. It is not any specific employer's system.
