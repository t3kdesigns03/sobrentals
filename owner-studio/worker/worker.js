/*
 * SOB Rentals — Owner Studio Worker  (name: sob-owner-studio)
 * -----------------------------------------------------------------------------
 * Purpose: let Sheila submit a NEW unit (form + drag-drop photos) without any
 * GitHub token in the browser. The Worker holds the only credential and:
 *   1. authenticates the owner passcode  (hashed, never plaintext in JS)
 *   2. best-effort scrapes a VRBO/Airbnb listing to pre-fill the form
 *   3. stores the submission as a DRAFT on an orphan-ish branch
 *      (owner-drafts/<id>) — nothing on main, nothing live
 *   4. fires a repository_dispatch so a GitHub Action emails Brandon
 *   5. Approve/Reject links (signed, ~7-day expiry) come back here; Approve
 *      fires the publish Action, Reject deletes the draft branch.
 *
 * Isolation: no custom route -> served from the default *.workers.dev host.
 * It therefore cannot overlap any spydernetwork.com route. Do not add a route
 * that shares a zone/path with spyder-hls-proxy / hls-proxxy.
 * -----------------------------------------------------------------------------
 */

const COMMUNITIES = [
  "Breakwater_Bay", "Compass_Point", "Golden_Reef", "Grandview_Point",
  "Harbor_Point", "Heron_Bay", "Houses", "Indian_Point", "Lands_End_Condos",
  "Ledges", "Palisades", "Parkside_Place", "Robins_Resort",
  "SouthwoodShores", "The_Knolls",
];

const enc = new TextEncoder();
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64urlToStr = (s) => {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return atob(s);
};

async function sha256hex(str) {
  const d = await crypto.subtle.digest("SHA-256", enc.encode(str));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}
async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}
async function signToken(payloadObj, secret) {
  const body = b64url(enc.encode(JSON.stringify(payloadObj)));
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  return body + "." + b64url(sig);
}
async function verifyToken(token, secret) {
  const [body, sig] = String(token || "").split(".");
  if (!body || !sig) return null;
  const key = await hmacKey(secret);
  const expected = b64url(await crypto.subtle.sign("HMAC", key, enc.encode(body)));
  if (!timingSafeEqual(sig, expected)) return null;
  let payload;
  try { payload = JSON.parse(b64urlToStr(body)); } catch { return null; }
  if (payload.exp && Date.now() > payload.exp) return null;
  return payload;
}

/* ---------- CORS + response helpers ---------- */
function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim());
  const allow = allowed.includes(origin) ? origin : allowed[0] || "*";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}
const json = (obj, status, extra) =>
  new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { "Content-Type": "application/json", ...(extra || {}) },
  });
const htmlPage = (title, body) =>
  new Response(`<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>${title}</title>
<style>body{font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;min-height:100vh;margin:0;align-items:center;justify-content:center;text-align:center;padding:24px}
.c{max-width:520px}h1{color:#f97316;margin:0 0 .5rem}p{color:#94a3b8;line-height:1.6}</style></head>
<body><div class="c">${body}</div></body></html>`,
    { headers: { "Content-Type": "text/html; charset=utf-8" } });

/* ---------- GitHub REST helper ---------- */
async function gh(env, path, method, body) {
  const res = await fetch(`https://api.github.com${path}`, {
    method: method || "GET",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "sob-owner-studio",
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const err = new Error(`GitHub ${method || "GET"} ${path} -> ${res.status}`);
    err.status = res.status; err.data = data;
    throw err;
  }
  return data;
}
const repoPath = (env, sub) => `/repos/${env.GH_OWNER}/${env.GH_REPO}${sub}`;

/* ---------- auth ---------- */
async function requireAuth(request, env) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  const payload = await verifyToken(token, env.SIGNING_SECRET);
  return payload && payload.sub === "owner" ? payload : null;
}

/* ---------- best-effort listing scrape ---------- */
async function handleScrape(request, env) {
  const { url } = await request.json().catch(() => ({}));
  const out = { ok: false, sourceUrl: url || "", title: "", description: "",
    beds: null, baths: null, sleeps: null, amenities: [] };
  if (!url || !/^https?:\/\//i.test(url)) return json(out);
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
      },
      cf: { cacheTtl: 0 },
    });
    if (!res.ok) return json(out);
    const html = (await res.text()).slice(0, 600000);
    const pick = (re) => { const m = html.match(re); return m ? m[1].trim() : ""; };
    const decode = (s) => s.replace(/&amp;/g, "&").replace(/&#39;/g, "'")
      .replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
    out.title = decode(
      pick(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i) ||
      pick(/<title[^>]*>([^<]+)<\/title>/i));
    out.description = decode(
      pick(/<meta[^>]+property=["']og:description["'][^>]+content=["']([^"']+)["']/i) ||
      pick(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']/i));
    const num = (re) => { const m = html.match(re); return m ? parseInt(m[1], 10) : null; };
    out.sleeps = num(/sleeps?\s*(\d+)/i) || num(/(\d+)\s*guests?/i);
    out.beds   = num(/(\d+)\s*bedrooms?/i) || num(/(\d+)\s*br\b/i);
    out.baths  = num(/(\d+)\s*bathrooms?/i) || num(/(\d+)\s*ba\b/i);
    const amen = [];
    for (const [kw, re] of [
      ["Free WiFi", /wi-?fi/i], ["Kitchen", /kitchen/i], ["Pool access", /pool/i],
      ["Hot tub", /hot tub|jacuzzi/i], ["Air conditioning", /air conditioning|\bac\b/i],
      ["Washer/Dryer", /washer|dryer|laundry/i], ["Boat dock", /boat|dock|slip/i],
      ["Grill", /grill|bbq/i], ["Fireplace", /fireplace/i], ["TV", /\btv\b|television/i],
    ]) if (re.test(html)) amen.push(kw);
    out.amenities = amen;
    out.ok = Boolean(out.title || out.description || out.sleeps);
  } catch (_e) { /* best-effort: return whatever we have */ }
  return json(out);
}

/* ---------- draft: start / photo / finish ---------- */
async function handleDraftStart(request, env) {
  const b = await request.json().catch(() => ({}));
  if (!COMMUNITIES.includes(b.community))
    return json({ ok: false, error: "unknown community" }, 400);
  const rnd = crypto.randomUUID().split("-")[0];
  const draftId = `${Date.now().toString(36)}-${rnd}`;
  const branch = `owner-drafts/${draftId}`;
  const mainRef = await gh(env, repoPath(env, `/git/ref/heads/${env.GH_BRANCH}`));
  const headSha = mainRef.object.sha;
  await gh(env, repoPath(env, "/git/refs"), "POST",
    { ref: `refs/heads/${branch}`, sha: headSha });
  return json({ ok: true, draftId, branch, headSha });
}

async function handleDraftPhoto(request, env) {
  const b = await request.json().catch(() => ({}));
  if (!b.draftId || typeof b.index !== "number" || !b.contentBase64)
    return json({ ok: false, error: "bad photo" }, 400);
  const nnn = String(b.index + 1).padStart(3, "0");
  const path = `_owner_drafts/${b.draftId}/photos/${nnn}.jpg`;
  const blob = await gh(env, repoPath(env, "/git/blobs"), "POST",
    { content: b.contentBase64, encoding: "base64" });
  return json({ ok: true, index: b.index, path, sha: blob.sha });
}

async function handleDraftFinish(request, env) {
  const b = await request.json().catch(() => ({}));
  const { draftId, branch, photos, manifest, coverIndex } = b;
  if (!draftId || !branch || !Array.isArray(photos) || !manifest)
    return json({ ok: false, error: "bad finish" }, 400);
  if (!COMMUNITIES.includes(manifest.community))
    return json({ ok: false, error: "unknown community" }, 400);

  const brRef = await gh(env, repoPath(env, `/git/ref/heads/${branch}`));
  const brSha = brRef.object.sha;
  const brCommit = await gh(env, repoPath(env, `/git/commits/${brSha}`));
  const baseTree = brCommit.tree.sha;

  const full = { ...manifest, draftId, branch, coverIndex: coverIndex || 0,
    photos: photos.map((p) => p.path), submittedAt: new Date().toISOString() };
  const previewHtml = buildPreview(full, env);

  const tree = photos.map((p) => ({ path: p.path, mode: "100644", type: "blob", sha: p.sha }));
  tree.push({ path: `_owner_drafts/${draftId}/manifest.json`, mode: "100644",
    type: "blob", content: JSON.stringify(full, null, 2) });
  tree.push({ path: `_owner_drafts/${draftId}/preview.html`, mode: "100644",
    type: "blob", content: previewHtml });

  const newTree = await gh(env, repoPath(env, "/git/trees"), "POST",
    { base_tree: baseTree, tree });
  const commit = await gh(env, repoPath(env, "/git/commits"), "POST",
    { message: `owner draft: ${manifest.community} / ${manifest.unit} (${draftId})`,
      tree: newTree.sha, parents: [brSha] });
  await gh(env, repoPath(env, `/git/refs/heads/${branch}`), "PATCH",
    { sha: commit.sha, force: true });

  // signed approve / reject links (~7 days)
  const exp = Date.now() + 7 * 24 * 3600 * 1000;
  const workerBase = new URL(request.url).origin;
  const approveTok = await signToken({ draftId, branch, act: "approve", exp }, env.SIGNING_SECRET);
  const rejectTok  = await signToken({ draftId, branch, act: "reject",  exp }, env.SIGNING_SECRET);
  const approveUrl = `${workerBase}/api/approve?t=${encodeURIComponent(approveTok)}`;
  const rejectUrl  = `${workerBase}/api/reject?t=${encodeURIComponent(rejectTok)}`;

  const raw = (p) => `https://raw.githubusercontent.com/${env.GH_OWNER}/${env.GH_REPO}/${branch}/${p}`
    .replace(/ /g, "%20");
  const thumbUrls = photos.slice(0, 6).map((p) => raw(p.path));
  const coverThumbUrl = raw(photos[coverIndex || 0]?.path || photos[0].path);
  const previewUrl = `https://htmlpreview.github.io/?https://raw.githubusercontent.com/${env.GH_OWNER}/${env.GH_REPO}/${branch}/_owner_drafts/${draftId}/preview.html`;

  await gh(env, repoPath(env, "/dispatches"), "POST", {
    event_type: "owner-draft",
    client_payload: {
      draftId, branch,
      community: manifest.community, unit: manifest.unit,
      beds: manifest.beds, baths: manifest.baths, sleeps: manifest.sleeps,
      title: manifest.title || "",
      descExcerpt: String(manifest.description || "").slice(0, 400),
      photoCount: photos.length,
      coverThumbUrl, thumbUrls, approveUrl, rejectUrl, previewUrl,
      sourceUrl: manifest.sourceUrl || "",
    },
  });
  return json({ ok: true, draftId });
}

function buildPreview(m, env) {
  const imgs = m.photos.map((p, i) =>
    `<img src="/${p}" alt="photo ${i + 1}" loading="lazy">`).join("");
  const amen = (m.amenities || []).map((a) => `<li>${a}</li>`).join("");
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Draft preview — ${m.community} ${m.unit}</title>
<style>body{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#f8fafc;color:#0f172a}
header{background:#0f172a;color:#fff;padding:20px 24px}header b{color:#f97316}
.wrap{max-width:1000px;margin:0 auto;padding:24px}
.specs{display:flex;gap:24px;flex-wrap:wrap;margin:8px 0 20px;color:#475569;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.grid img{width:100%;height:170px;object-fit:cover;border-radius:8px}
.pill{display:inline-block;background:#fee2d5;color:#c2410c;border-radius:999px;padding:4px 12px;font-size:.8rem;font-weight:700}
ul{columns:2;color:#334155}</style></head>
<body><header><span class="pill">PENDING DRAFT — not live</span>
<h1 style="margin:.4rem 0 0">${m.community.replace(/_/g, " ")} · <b>${m.unit}</b></h1></header>
<div class="wrap">
<div class="specs"><span>🛏 ${m.beds} Bed</span><span>🛁 ${m.baths} Bath</span><span>👥 Sleeps ${m.sleeps}</span><span>📷 ${m.photos.length} photos</span></div>
<h2>${m.title || ""}</h2>
<p style="line-height:1.7;color:#334155;max-width:70ch">${(m.description || "").replace(/</g, "&lt;")}</p>
${amen ? `<h3>Amenities</h3><ul>${amen}</ul>` : ""}
<h3>Photos</h3><div class="grid">${imgs}</div>
${m.sourceUrl ? `<p style="margin-top:24px"><a href="${m.sourceUrl}">Source listing</a></p>` : ""}
</div></body></html>`;
}

/* ---------- approve / reject ---------- */
async function handleApprove(request, env) {
  const t = new URL(request.url).searchParams.get("t");
  const p = await verifyToken(t, env.SIGNING_SECRET);
  if (!p || p.act !== "approve")
    return htmlPage("Link expired", "<h1>Link expired</h1><p>This approval link is invalid or older than 7 days. Ask Sheila to re-submit.</p>");
  try {
    await gh(env, repoPath(env, "/dispatches"), "POST",
      { event_type: "owner-publish", client_payload: { draftId: p.draftId, branch: p.branch } });
  } catch (e) {
    return htmlPage("Error", `<h1>Could not start publish</h1><p>${e.message}</p>`);
  }
  return htmlPage("Approved",
    `<h1>Approved ✓</h1><p>Publishing <b>${p.draftId}</b> now. The unit will appear on sobrentals.com within a couple of minutes once Pages rebuilds. You can close this tab.</p>`);
}
async function handleReject(request, env) {
  const t = new URL(request.url).searchParams.get("t");
  const p = await verifyToken(t, env.SIGNING_SECRET);
  if (!p || p.act !== "reject")
    return htmlPage("Link expired", "<h1>Link expired</h1><p>This link is invalid or older than 7 days.</p>");
  try {
    await gh(env, repoPath(env, `/git/refs/heads/${p.branch}`), "DELETE");
  } catch (e) {
    if (e.status !== 422 && e.status !== 404)
      return htmlPage("Error", `<h1>Could not discard</h1><p>${e.message}</p>`);
  }
  return htmlPage("Rejected", `<h1>Rejected ✕</h1><p>Draft <b>${p.draftId}</b> was discarded. Nothing was published.</p>`);
}

/* ---------- login ---------- */
async function handleLogin(request, env) {
  const { passcode } = await request.json().catch(() => ({}));
  if (!passcode) return json({ ok: false }, 400);
  const h = await sha256hex((env.OWNER_SALT || "") + passcode);
  if (!timingSafeEqual(h, env.OWNER_HASH || ""))
    return json({ ok: false, error: "Incorrect passcode" }, 401);
  const token = await signToken({ sub: "owner", exp: Date.now() + 2 * 3600 * 1000 }, env.SIGNING_SECRET);
  return json({ ok: true, token });
}

/* ---------- router ---------- */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const withCors = (resp) => {
      const r = new Response(resp.body, resp);
      for (const [k, v] of Object.entries(cors)) r.headers.set(k, v);
      return r;
    };
    try {
      const p = url.pathname;
      // GET link endpoints (clicked from email) — no CORS/auth, token-signed
      if (request.method === "GET" && p === "/api/approve") return handleApprove(request, env);
      if (request.method === "GET" && p === "/api/reject")  return handleReject(request, env);
      if (request.method === "GET" && (p === "/" || p === "/health"))
        return htmlPage("Owner Studio API", "<h1>sob-owner-studio</h1><p>API is running. The owner tool lives at sobrentals.com/owner/.</p>");

      if (request.method !== "POST") return withCors(json({ ok: false, error: "method" }, 405));
      if (p === "/api/login") return withCors(await handleLogin(request, env));

      // everything below needs a valid session token
      if (!(await requireAuth(request, env))) return withCors(json({ ok: false, error: "unauthorized" }, 401));
      if (p === "/api/scrape")        return withCors(await handleScrape(request, env));
      if (p === "/api/draft/start")   return withCors(await handleDraftStart(request, env));
      if (p === "/api/draft/photo")   return withCors(await handleDraftPhoto(request, env));
      if (p === "/api/draft/finish")  return withCors(await handleDraftFinish(request, env));
      return withCors(json({ ok: false, error: "not found" }, 404));
    } catch (e) {
      return withCors(json({ ok: false, error: e.message, detail: e.data || null }, e.status || 500));
    }
  },
};
