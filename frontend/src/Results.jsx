import { useState } from "react";

const STATUS = {
  PASS: { label: "Passes screening", cls: "good" },
  WOULD_BE_REJECTED: { label: "Would be auto-rejected", cls: "bad" },
  NEEDS_REVIEW: { label: "Couldn't read resume", cls: "warn" },
};

const KIND_LABEL = { knockout: "Lifts Required %", required: "Required item", gate: "Raises skill gate", skill: "Skill", quality: "Quality", integrity: "Integrity" };

function Ring({ score }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  return (
    <svg className="ring" viewBox="0 0 128 128" role="img" aria-label={`Score ${score} out of 100`}>
      <circle cx="64" cy="64" r={r} className="ring-track" />
      <circle
        cx="64"
        cy="64"
        r={r}
        className="ring-fill"
        strokeDasharray={`${c * pct} ${c}`}
        transform="rotate(-90 64 64)"
      />
      <text x="64" y="62" textAnchor="middle" className="ring-num">{score}</text>
      <text x="64" y="84" textAnchor="middle" className="ring-sub">/ 100</text>
    </svg>
  );
}

function Dimension({ d }) {
  const [open, setOpen] = useState(false);
  const pct = d.weight ? (d.points / d.weight) * 100 : 0;
  return (
    <div className="dim">
      <button type="button" className="dim-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="dim-name">
          <span className="muted">{d.id}</span> {d.name}
        </span>
        <span className="dim-pts">
          {d.points.toFixed(1)} <span className="muted">/ {d.weight}</span>
        </span>
        <span className="bar">
          <span style={{ width: `${pct}%` }} />
        </span>
      </button>
      {open && (
        <div className="dim-body">
          {d.bonus > 0 && <p className="small">Includes +{d.bonus} renowned-institute bonus (the JD prefers it).</p>}
          {d.evidence?.length > 0 && (
            <>
              <span className="lbl">Evidence</span>
              <ul>{d.evidence.map((e, i) => <li key={i}>“{e}”</li>)}</ul>
            </>
          )}
          {d.gaps?.length > 0 && (
            <>
              <span className="lbl">Gaps</span>
              <ul>{d.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
            </>
          )}
          {!d.evidence?.length && !d.gaps?.length && <p className="muted small">Nothing to flag.</p>}
        </div>
      )}
    </div>
  );
}

export default function Results({ result }) {
  const st = STATUS[result.status] || STATUS.NEEDS_REVIEW;
  if (result.status === "NEEDS_REVIEW") {
    return (
      <div className="card">
        <span className={`badge ${st.cls}`}>{st.label}</span>
        <p>{result.message}</p>
      </div>
    );
  }
  const gate = result.skill_gate;
  const req = result.required_gate;
  const redFlags = result.knockouts.filter((k) => k.hard && !k.passed);
  const missed = result.knockouts.filter((k) => !k.hard && !k.passed);
  return (
    <div className="results">
      <div className="card summary">
        <Ring score={result.score} />
        <div>
          <span className={`badge ${st.cls}`}>{st.label}</span>
          <h2>
            {result.band} <span className="muted">· {result.level} role</span>
          </h2>
          <p>{result.band_action}</p>
          {(!req.passed || !gate.passed) && (
            <ul className="blockers">
              {redFlags.map((k) => (
                <li key={k.rule_id}>{k.reason}</li>
              ))}
              {!req.passed && !req.red_flag_hit && (
                <li>
                  Required criteria {req.coverage}% met, below the {req.threshold}% threshold
                </li>
              )}
              {!gate.passed && (
                <li>
                  Technical skill score {gate.score.toFixed(1)} is below the cutoff of {gate.cutoff}
                </li>
              )}
            </ul>
          )}
          <p className="muted small">{result.yoe} years of relevant experience · {result.page_count} page(s)</p>
        </div>
      </div>

      <div className="card">
        <h3>Technical skill gate</h3>
        <div className="gate">
          <div className="gate-bar">
            <span className={gate.passed ? "good" : "bad"} style={{ width: `${gate.score * 10}%` }} />
            <i style={{ left: `${gate.cutoff * 10}%` }} title={`Cutoff ${gate.cutoff}`} />
          </div>
          <span className="num">
            {gate.score.toFixed(1)} <span className="muted">/ 10 · cutoff {gate.cutoff}</span>
          </span>
        </div>
        <table className="skills">
          <thead>
            <tr><th>Skill</th><th>Match</th><th>Evidence</th><th>Last used</th></tr>
          </thead>
          <tbody>
            {result.competencies.map((c, i) => (
              <tr key={i}>
                <td>
                  <span className={`dot ${c.importance}`} /> {c.name}
                </td>
                <td className={c.match === "none" ? "bad-text" : ""}>{c.match}</td>
                <td>{c.evidence_type.replace("_", " ")}</td>
                <td>{c.last_used || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {result.fixes?.length > 0 && (
        <div className="card">
          <h3>What to fix first</h3>
          <ol className="fixes">
            {result.fixes.map((f) => (
              <li key={f.rank}>
                <div>
                  <span className={`tag tag-${f.kind}`}>{KIND_LABEL[f.kind] || f.kind}</span>
                  <p>{f.action}</p>
                </div>
                <span className="gain">
                  +{f.est_gain} pts
                  {f.kind === "gate" && <small className="muted">gate +{f.skill_gate_gain}</small>}
                </span>
              </li>
            ))}
          </ol>
          <p className="muted small">Gains are estimated by rescoring with that gap closed. Only add what is true.</p>
        </div>
      )}

      <div className="card">
        <h3>
          Required criteria
          {missed.length > 0 && <span className="muted">· {missed.length} flagged</span>}
        </h3>
        {req.items > 0 ? (
          <div className="gate">
            <div className="gate-bar">
              <span className={req.coverage >= req.threshold ? "good" : "bad"} style={{ width: `${req.coverage}%` }} />
              <i style={{ left: `${req.threshold}%` }} title={`Threshold ${req.threshold}%`} />
            </div>
            <span className="num">
              {req.coverage}% <span className="muted">met · threshold {req.threshold}%</span>
            </span>
          </div>
        ) : (
          <p className="muted small">The JD sets no Required items.</p>
        )}
        <ul className="kos">
          {result.knockouts.map((k) => (
            <li key={k.rule_id} className={k.status}>
              <span className="mark">{k.status === "met" ? "✓" : k.status === "partial" ? "½" : "✕"}</span>
              <div>
                <span>{k.rule}</span>
                {k.hard && !k.passed && <span className="tag tag-knockout">Hard knockout</span>}
                {k.reason && <p className={`small ${k.hard ? "bad-text" : "warn-text"}`}>{k.reason}</p>}
                {k.evidence && <p className="small muted">“{k.evidence}”</p>}
              </div>
            </li>
          ))}
        </ul>
        <p className="muted small">
          Each Required item earns full, half or no credit. Missed items are flagged; the resume is only rejected when
          coverage drops below the threshold, or when a JD red flag matches.
        </p>
      </div>

      <div className="card">
        <h3>Fit breakdown</h3>
        {result.dimensions.map((d) => <Dimension key={d.id} d={d} />)}
      </div>

      {(result.penalties.length > 0 || result.flags.length > 0) && (
        <div className="card">
          <h3>Integrity</h3>
          {result.penalties.map((p, i) => (
            <p key={i}>
              <span className="bad-text">{p.points}</span> {p.check.replace(/_/g, " ")}: <span className="muted">{p.detail}</span>
            </p>
          ))}
          {result.flags.length > 0 && <p className="small muted">Flags: {result.flags.join(", ")}</p>}
        </div>
      )}

      <p className="muted small disclaimer">{result.disclaimer}</p>
    </div>
  );
}
