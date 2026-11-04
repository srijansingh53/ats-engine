async function handle(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) throw new Error(body?.error || `Request failed (${res.status})`);
  return body;
}

export async function health() {
  return handle(await fetch("/api/health"));
}

export async function extractJD(jdText) {
  const res = await fetch("/api/jd/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jd_text: jdText }),
  });
  return (await handle(res)).jd;
}

export async function scoreResume({ file, jd, jdText, level }) {
  const form = new FormData();
  form.append("resume", file);
  if (jd) form.append("jd", JSON.stringify(jd));
  form.append("jd_text", jdText || "");
  if (level && level !== "auto") form.append("level", level);
  return handle(await fetch("/api/score", { method: "POST", body: form }));
}
