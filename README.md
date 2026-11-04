# ATS Engine

This tool scores a resume against a software engineering job description (entry or senior roles) out of 100. It explains every point and returns ranked, gain-estimated fixes. It is candidate-facing: it tells you whether a typical ATS would filter you out and what to change first.

**Stack:** Flask (Python 3.13) + React 18 (Vite), with Claude for extraction and rubric judging. Everything ships as one Docker image.

Product spec: [`PRD/ATS-Engine-PRD.md`](PRD/ATS-Engine-PRD.md).

## How scoring works

| Layer | What it does | Outcome |
| --- | --- | --- |
| L0 Parse | PDF, DOCX or TXT to text. Detects white, tiny or off-page text and counts pages | `NEEDS_REVIEW` if unreadable |
| L1 Required criteria | % of Required items met (skills, YoE, experience, degree, certs; partial credit) vs threshold (default 70%). JD red flags are hard knockouts | `WOULD_BE_REJECTED` below threshold, flags above |
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

| Option | Setup | Cost (approx.) | Notes |
| --- | --- | --- | --- |
| **Render** (recommended) | New → Blueprint → this repo (`render.yaml`). Enter `ANTHROPIC_API_KEY` when prompted | Free tier sleeps; Starter about $7/mo | Auto-deploys on push, HTTPS and health checks included. Singapore region |
| **Fly.io** | `fly launch --copy-config --no-deploy` → `fly secrets set ANTHROPIC_API_KEY=...` → `fly deploy` | Pay as you go; about $2–5/mo with auto-stop | Mumbai (`bom`) region, scales to zero |
| **Railway** | New Project → Deploy from GitHub → add `ANTHROPIC_API_KEY` | Usage-based, about $5/mo | Simplest UI. Detects the Dockerfile |
| **Google Cloud Run** | `gcloud run deploy ats-engine --source . --region asia-south1 --set-secrets ANTHROPIC_API_KEY=...` | Free tier covers light use | Scales to zero. Set `--timeout 150` |
| **Your own VM** (EC2, Lightsail, DigitalOcean) | `docker run -d -p 80:8000 --env-file .env --restart unless-stopped ghcr.io/<owner>/ats-engine` | About $5/mo | You manage TLS (Caddy or nginx) and updates |

GitHub Pages can't host this app on its own, because it only serves static files and the scoring API needs a server.

## Production notes

- **Cost protection:** `/api/score` is rate-limited per IP (default 10 per hour and 30 per day). Resume text is capped at 30K characters and the JD at 20K. Every Claude call has a 90 s timeout and 2 retries. Set a monthly spend limit in the Anthropic Console as well.
- **Private mode:** set `ACCESS_TOKEN`. The UI then asks for it once and sends it as `X-Access-Token`.
- **Multiple instances:** rate limits and the LLM cache live in memory per worker. For exact limits across instances, set `RATE_LIMIT_STORAGE_URI=redis://...`.
- **Security:** CSP, `nosniff`, `frame-ancestors 'none'` and HSTS (over HTTPS) are set on every response. Uploads are checked by magic bytes. Errors return a request ID and never internal details.
- **Privacy:** resumes are processed in memory and never written to disk or logged. Only method, path, status and latency are logged.
- **Observability:** every API response carries `X-Request-ID`, which matches the server log line.
- **Health check:** `GET /api/health`, also used by Docker `HEALTHCHECK`, Render and Fly.

All settings are in [`.env.example`](.env.example).

## API

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | none | `{ok, llm_configured, auth_required}` |
| POST | `/api/jd/extract` | `{jd_text}` | `{jd}`: structured requirements (editable) |
| POST | `/api/score` | multipart: `resume` file, plus `jd` (JSON) or `jd_text`, optional `level` | Full report: status, score, band, skill gate, knockouts, dimensions, penalties, flags, fixes |

## Project layout

```
backend/
  ats/__init__.py        Flask app factory, routes, rate limits, security headers
  ats/validation.py      bounds-checks client-edited JD requirements
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
Dockerfile               multi-stage: build React, serve with gunicorn (gunicorn.conf.py)
render.yaml / fly.toml   one-click deploy configs
```

The score approximates typical ATS screening. It is not any specific employer's system.
