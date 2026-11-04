import { useEffect, useRef, useState } from "react";
import { extractJD, getToken, health, scoreResume, setToken } from "./api.js";
import JDEditor from "./JDEditor.jsx";
import Results from "./Results.jsx";

export default function App() {
  const [jdText, setJdText] = useState("");
  const [jd, setJd] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [apiInfo, setApiInfo] = useState(null);
  const [token, setTokenState] = useState(getToken());
  const [needToken, setNeedToken] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef(null);
  const resultsRef = useRef(null);

  useEffect(() => {
    health()
      .then((h) => {
        setApiInfo(h);
        if (h.auth_required && !getToken()) setNeedToken(true);
      })
      .catch(() => setApiInfo({ ok: false }));
  }, []);

  const run = async (label, fn) => {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
      if (e.status === 401) setNeedToken(true);
    } finally {
      setBusy("");
    }
  };

  const onExtract = () => run("Reading the job description…", async () => setJd(await extractJD(jdText)));

  const onScore = () =>
    run("Scoring your resume…", async () => {
      const r = await scoreResume({ file, jd, jdText });
      setResult(r);
      if (!jd && r.jd) setJd(r.jd);
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    });

  const pick = (f) => {
    if (!f) return;
    if (!/\.(pdf|docx|txt)$/i.test(f.name)) {
      setError("Upload a PDF, DOCX or TXT file.");
      return;
    }
    setFile(f);
    setError("");
  };

  const canScore = file && (jd || jdText.trim().length >= 50) && !busy;

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo" aria-hidden="true">✓</span>
          <div>
            <h1>ATS Engine</h1>
            <p className="muted">Score your resume against a software engineering JD, see why, and fix what matters.</p>
          </div>
        </div>
        {needToken && (
          <form
            className="banner token"
            onSubmit={(e) => {
              e.preventDefault();
              setToken(token.trim());
              setNeedToken(false);
              setError("");
            }}
          >
            <span>This deployment needs an access token.</span>
            <input
              type="password"
              value={token}
              onChange={(e) => setTokenState(e.target.value)}
              placeholder="Access token"
              aria-label="Access token"
            />
            <button type="submit" className="ghost">Save</button>
          </form>
        )}
        {apiInfo && apiInfo.ok === false && (
          <p className="banner">Can't reach the scoring server.</p>
        )}
        {apiInfo && apiInfo.ok && !apiInfo.llm_configured && (
          <p className="banner">The server has no ANTHROPIC_API_KEY set, so scoring won't work until it does.</p>
        )}
      </header>

      <main>
        <div className="inputs">
          <div className="card">
            <h3><span className="step">1</span> Job description</h3>
            <textarea
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              placeholder="Paste the full job description here…"
              rows={jd ? 5 : 12}
            />
            <div className="actions">
              <button type="button" className="ghost" disabled={jdText.trim().length < 50 || !!busy} onClick={onExtract}>
                {jd ? "Re-extract requirements" : "Extract requirements"}
              </button>
              <span className="muted small">Optional. Lets you review and edit Required vs Preferred before scoring.</span>
            </div>
            {jd && <JDEditor jd={jd} setJd={setJd} />}
          </div>

          <div className="card">
            <h3><span className="step">2</span> Your resume</h3>
            <div
              className={`drop ${drag ? "drag" : ""} ${file ? "has" : ""}`}
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                pick(e.dataTransfer.files[0]);
              }}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
            >
              {file ? (
                <>
                  <strong>{file.name}</strong>
                  <span className="muted small">{(file.size / 1024).toFixed(0)} KB · click to replace</span>
                </>
              ) : (
                <>
                  <strong>Drop your resume here or click to upload</strong>
                  <span className="muted small">PDF, DOCX or TXT, up to 5 MB</span>
                </>
              )}
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.txt"
                hidden
                onChange={(e) => pick(e.target.files[0])}
              />
            </div>
            <button type="button" className="primary" disabled={!canScore} onClick={onScore}>
              Score my resume
            </button>
            <p className="muted small privacy">
              Your resume is processed in memory and never stored. Its text is sent to Anthropic's API for analysis.
            </p>
          </div>

          {busy && <p className="busy"><span className="spinner" /> {busy}</p>}
          {error && <p className="error" role="alert">{error}</p>}
        </div>

        <div className="output" ref={resultsRef}>
          {result ? (
            <Results result={result} />
          ) : (
            <div className="card empty">
              <h3>How scoring works</h3>
              <ol className="layers">
                <li><b>Parse</b>: reads your resume and the JD into structured data, with personal details ignored.</li>
                <li><b>Required criteria</b>: the share of Required items met, with partial credit, checked against a threshold (default 70%). JD red flags are hard knockouts.</li>
                <li><b>Skill gate</b>: a 0–10 technical score, weighted by evidence and recency, checked against a cutoff.</li>
                <li><b>Fit score</b>: 8 dimensions, weighted differently for entry and senior roles.</li>
                <li><b>Integrity</b>: penalties for hidden text, keyword stuffing, copying the JD and date conflicts.</li>
                <li><b>Band and fixes</b>: Strong, Good, Borderline or Weak, plus ranked fixes with estimated gains.</li>
              </ol>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
