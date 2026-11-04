import { useState } from "react";

function Toggle({ value, onChange }) {
  return (
    <div className="toggle" role="group" aria-label="Importance">
      {["preferred", "required"].map((v) => (
        <button
          key={v}
          type="button"
          className={value === v ? `on ${v}` : ""}
          onClick={() => onChange(v)}
        >
          {v === "required" ? "Required" : "Preferred"}
        </button>
      ))}
    </div>
  );
}

function ItemList({ items, label, getText, onChange, placeholder, makeItem, hasImportance = true }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const t = draft.trim();
    if (!t) return;
    onChange([...items, makeItem(t)]);
    setDraft("");
  };
  return (
    <div className="itemlist">
      {items.length === 0 && <p className="muted small">None yet.</p>}
      {items.map((it, i) => (
        <div className="item" key={i}>
          <span className={`dot ${hasImportance ? it.importance : "flag"}`} />
          <span className="item-text">{getText(it)}</span>
          {hasImportance && (
            <Toggle
              value={it.importance}
              onChange={(v) => onChange(items.map((x, j) => (j === i ? { ...x, importance: v } : x)))}
            />
          )}
          <button
            type="button"
            className="icon"
            aria-label={`Remove ${label}`}
            onClick={() => onChange(items.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      ))}
      <div className="add">
        <input
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="ghost" onClick={add}>
          Add
        </button>
      </div>
    </div>
  );
}

function OptionalReq({ value, onChange, placeholder }) {
  if (!value)
    return (
      <div className="add">
        <input
          placeholder={placeholder}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.target.value.trim()) {
              e.preventDefault();
              onChange({ text: e.target.value.trim(), importance: "preferred" });
            }
          }}
        />
      </div>
    );
  return (
    <div className="item">
      <span className={`dot ${value.importance}`} />
      <span className="item-text">{value.text}</span>
      <Toggle value={value.importance} onChange={(v) => onChange({ ...value, importance: v })} />
      <button type="button" className="icon" aria-label="Remove" onClick={() => onChange(null)}>
        ×
      </button>
    </div>
  );
}

export default function JDEditor({ jd, setJd }) {
  const set = (k, v) => setJd({ ...jd, [k]: v });
  return (
    <div className="jd-editor">
      <div className="row two">
        <label>
          <span className="lbl">Role title</span>
          <input value={jd.title || ""} onChange={(e) => set("title", e.target.value)} />
        </label>
        <label>
          <span className="lbl">Level</span>
          <select
            value={jd.level}
            onChange={(e) => setJd({ ...jd, level: e.target.value, skill_cutoff: e.target.value === "senior" ? 7 : 6 })}
          >
            <option value="entry">Entry (0–2 yrs)</option>
            <option value="senior">Senior (5+ yrs)</option>
          </select>
        </label>
      </div>

      <section>
        <h4>Competencies</h4>
        <p className="hint">Required skills count toward the Required criteria threshold below. Preferred skills only add points.</p>
        <ItemList
          label="competency"
          items={jd.competencies || []}
          getText={(c) => c.name}
          placeholder="Add a skill, e.g. Python or FastAPI or Flask"
          makeItem={(t) => ({ name: t, alternatives: t.split(/\s+or\s+|\//i).map((s) => s.trim()), importance: "required" })}
          onChange={(v) => set("competencies", v)}
        />
      </section>

      <section>
        <h4>Work experience</h4>
        <label className="inline">
          <span className="lbl">Minimum years</span>
          <input
            type="number"
            min="0"
            max="30"
            step="0.5"
            value={jd.min_yoe ?? ""}
            onChange={(e) => set("min_yoe", e.target.value === "" ? null : Number(e.target.value))}
          />
        </label>
        <ItemList
          label="experience"
          items={jd.experience_requirements || []}
          getText={(x) => x.text}
          placeholder="e.g. Experience building high-throughput APIs"
          makeItem={(t) => {
            const m = t.match(/(\d+(\.\d+)?)\s*\+?\s*(years|yrs)/i);
            return { text: t, min_yoe: m ? Number(m[1]) : null, importance: "preferred" };
          }}
          onChange={(v) => set("experience_requirements", v)}
        />
      </section>

      <section>
        <h4>Education</h4>
        <span className="lbl">Degree</span>
        <OptionalReq value={jd.degree} onChange={(v) => set("degree", v)} placeholder="e.g. B.Tech in CS or related" />
        <span className="lbl">College</span>
        <p className="hint">A renowned college only adds bonus points (up to +3) when this is set. No one loses points for not having it.</p>
        <OptionalReq
          value={jd.college_preference}
          onChange={(v) => set("college_preference", v && { ...v, importance: "preferred" })}
          placeholder="e.g. Tier 1 university is preferred"
        />
        <span className="lbl">Certifications</span>
        <ItemList
          label="certification"
          items={jd.certifications || []}
          getText={(c) => c.text}
          placeholder="e.g. AWS Solutions Architect"
          makeItem={(t) => ({ text: t, importance: "preferred" })}
          onChange={(v) => set("certifications", v)}
        />
      </section>

      <section>
        <h4>Red flags</h4>
        <p className="hint">Disqualifiers stated in the JD. These stay hard knockouts: a match means the resume would be rejected.</p>
        <ItemList
          label="red flag"
          hasImportance={false}
          items={jd.red_flags || []}
          getText={(x) => x}
          placeholder="e.g. No production backend experience"
          makeItem={(t) => t}
          onChange={(v) => set("red_flags", v)}
        />
      </section>

      <section>
        <h4>Required criteria threshold</h4>
        <div className="slider">
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            value={jd.required_threshold ?? 70}
            onChange={(e) => set("required_threshold", Number(e.target.value))}
          />
          <span className="num">{Number(jd.required_threshold ?? 70)}%</span>
        </div>
        <p className="hint">The share of Required items (skills, experience, degree, certs) a resume must meet. Partial matches earn half credit. Missed items below 100% are flagged, not rejected.</p>
      </section>

      <section>
        <h4>Technical skill cutoff</h4>
        <div className="slider">
          <input
            type="range"
            min="0"
            max="10"
            step="0.5"
            value={jd.skill_cutoff ?? 6}
            onChange={(e) => set("skill_cutoff", Number(e.target.value))}
          />
          <span className="num">{Number(jd.skill_cutoff ?? 6).toFixed(1)} / 10</span>
        </div>
        <p className="hint">A technical skill score below this means the resume would be rejected. It covers technical skills only, not overall fit.</p>
      </section>
    </div>
  );
}
