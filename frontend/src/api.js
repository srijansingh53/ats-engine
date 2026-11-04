const TOKEN_KEY = "ats_access_token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

function headers(extra = {}) {
  const t = getToken();
  return t ? { ...extra, "X-Access-Token": t } : extra;
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function handle(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    let msg = body?.error || `Request failed (${res.status})`;
    if (body?.request_id) msg += ` (ref ${body.request_id})`;
    throw new ApiError(msg, res.status);
  }
  return body;
}

export async function health() {
  return handle(await fetch("/api/health"));
}

export async function extractJD(jdText) {
  const res = await fetch("/api/jd/extract", {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
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
  return handle(await fetch("/api/score", { method: "POST", body: form, headers: headers() }));
}
