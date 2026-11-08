const LEVEL_WORD = { normal: "Normal", watch: "Tight", alert: "Grid alert", emergency: "Emergency" };
let chartDay = null;

function statusLine(p) {
  const a = p.alert;
  switch (p.status) {
    case "ok": return `OK at ${p.last_ok}`;
    case "waiting": return `Waiting for today's check-in (by ${p.cutoff})`;
    case "asked": return "Asked to press I'm OK";
    case "help": return `Pressed HELP · asking ${a.asking}`;
    case "alert": return `${a.reason} · asking ${a.asking}`;
    case "visitor": return `${a.going} is going · about ${a.eta}`;
  }
}

function personCard(p) {
  const a = p.alert;
  const card = el("article", { class: `person ${p.status}` },
    el("header", {},
      el("h3", {}, p.name, " ", el("span", { class: "muted small" }, p.community)),
      p.simulated ? el("span", { class: "tag" }, "simulated") : el("span", { class: "tag" }, "real box")),
    el("div", { class: `status ${p.status}` }, statusLine(p)));
  if (a && a.message) {
    card.append(el("p", { class: "msg", dir: "auto" }, a.message,
      el("small", {}, a.message_source === "gemini" ? "Message worded by Gemini from the rule's facts" : "Message from a template")));
  }
  if (a) {
    card.append(el("div", { class: "row" },
      el("span", { class: "small muted" }, "Next: " + (a.chain.slice(a.step + 1).join(" → ") || "nobody")),
      el("button", { class: "btn", onclick: () => act(a.id, "cant") }, "Skip to next person"),
      el("button", { class: "btn", onclick: () => act(a.id, "resolved") }, "Mark resolved")));
  }
  return card;
}

function stat(label, value, cls) {
  return el("div", { class: "stat" }, el("b", { class: cls || "" }, value), el("span", {}, label));
}

function render(s) {
  document.getElementById("clock").textContent = s.clock;
  document.getElementById("mode").textContent =
    s.mode === "replay" ? `Replay · ${s.speed ? s.speed + "× speed" : "paused"}` : "Live";
  const c = s.conditions;
  document.getElementById("stats").replaceChildren(
    stat("Outside, Calgary", c.temp_c == null ? "–" : `${Math.round(c.temp_c)} °C`),
    stat("Alberta grid", LEVEL_WORD[c.level] || c.level, `level ${c.level}`),
    stat("Demand", c.ail_mw == null ? "–" : `${Math.round(c.ail_mw).toLocaleString()} MW`),
    c.price != null ? stat("Pool price", `$${c.price.toFixed(2)}/MWh`)
                    : stat("Supply cushion", c.cushion_mw == null ? "–" : `${Math.round(c.cushion_mw)} MW`));
  document.querySelectorAll(".speed").forEach(b =>
    b.setAttribute("aria-pressed", s.mode === "replay" && Number(b.dataset.speed) === s.speed));
  const order = { help: 0, alert: 1, visitor: 2, asked: 3, waiting: 4, ok: 5 };
  const people = [...s.residents].sort((x, y) => order[x.status] - order[y.status]);
  document.getElementById("people").replaceChildren(...people.map(personCard));
  document.getElementById("feed").replaceChildren(...s.feed.map(f =>
    el("li", {}, el("time", {}, new Date(f.t).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", timeZone: "America/Edmonton" })),
      el("span", { class: f.kind }, f.text))));
  if (c.error) document.getElementById("banner").replaceChildren(el("div", { class: "banner" }, "Live data: " + c.error));
  else if (document.getElementById("banner").textContent.startsWith("Live data")) document.getElementById("banner").replaceChildren();
  const day = s.now.slice(0, 10);
  if (day !== chartDay) { chartDay = day; drawChart(day); }
  else moveNowLine(s.now);
}

// ---- chart: demand line, price line, AESO events, a line for "now" -----------
let chartScale = null;
async function drawChart(day) {
  const g = await api(`/api/grid/day/${day}`);
  const svg = document.getElementById("chart");
  const W = 640, H = 230, L = 46, R = 46, T = 18, B = 26;
  const x = h => L + (h / 24) * (W - L - R);
  const ail = g.rows.map(r => r.ail_mw), lo = Math.min(...ail, 1e9) - 200, hi = Math.max(...ail, 0) + 200;
  const yA = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const yP = v => T + (1 - v / 1000) * (H - T - B);
  const hourOf = t => { const d = new Date(t); return Number(d.toLocaleString("en-CA", { hour: "numeric", hour12: false, timeZone: "America/Edmonton" })) % 24 + d.getMinutes() / 60; };
  const path = (rows, key, y) => rows.map((r, i) => `${i ? "L" : "M"}${x(hourOf(r.time) + 0.5).toFixed(1)},${y(r[key]).toFixed(1)}`).join("");
  const parts = [];
  for (let h = 0; h <= 24; h += 6) parts.push(`<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${H - B}" stroke="#2c3748"/><text x="${x(h)}" y="${H - 8}" text-anchor="middle">${h === 24 ? "" : (h % 12 || 12) + (h < 12 ? " am" : " pm")}</text>`);
  if (g.rows.length) {
    parts.push(`<path d="${path(g.rows, "price", yP)}" fill="none" stroke="#a9b1bd" stroke-width="1.5" stroke-dasharray="4 3"/>`);
    parts.push(`<path d="${path(g.rows, "ail_mw", yA)}" fill="none" stroke="#ffb547" stroke-width="2.5"/>`);
    parts.push(`<text x="${L - 6}" y="${yA(hi - 200)}" text-anchor="end">${Math.round(hi - 200).toLocaleString()}</text><text x="${L - 6}" y="${yA(lo + 200)}" text-anchor="end">${Math.round(lo + 200).toLocaleString()}</text>`);
    parts.push(`<text x="${W - R + 6}" y="${yP(1000) + 4}">$1000</text><text x="${W - R + 6}" y="${yP(0)}">$0</text>`);
  }
  g.events.forEach((e, i) => {
    const ex = x(hourOf(e.time));
    parts.push(`<g><title>${e.text}</title><line x1="${ex}" x2="${ex}" y1="${T}" y2="${H - B}" stroke="${e.level === "emergency" ? "#ff5a5a" : "#f0a04b"}" stroke-width="1"/><circle cx="${ex}" cy="${T - 6}" r="5" fill="${e.level === "emergency" ? "#ff5a5a" : "#f0a04b"}"/><text x="${ex}" y="${T - 3}" text-anchor="middle" style="fill:#0f141c;font-size:8px;font-weight:700">${i + 1}</text></g>`);
  });
  parts.push(`<line id="nowline" y1="${T}" y2="${H - B}" stroke="#f3eee4" stroke-width="1.5"/>`);
  svg.innerHTML = parts.join("");
  chartScale = { x, hourOf };
  document.getElementById("chart-note").textContent = g.rows.length
    ? `Amber: Alberta demand (MW). Dashed: pool price ($/MWh). Numbered marks: AESO grid events. Source: ${g.source === "aeso_ets_2024" ? "AESO pool price report and the Market Surveillance Administrator's event report" : "AESO Current Supply Demand API"}. Stored in ${window.storeKind}.`
    : "No readings stored for this day yet.";
}

function moveNowLine(now) {
  const line = document.getElementById("nowline");
  if (!line || !chartScale) return;
  const nx = chartScale.x(chartScale.hourOf(now));
  line.setAttribute("x1", nx); line.setAttribute("x2", nx);
}

// ---- actions ---------------------------------------------------------------
async function act(id, action) { await api(`/api/alerts/${id}/${action}`, {}); refresh(); }
async function setMode(mode, speed) { await api("/api/mode", { mode, speed }); chartDay = null; refresh(); }
async function setSpeed(speed) { await api("/api/speed", { speed }); refresh(); }

async function refresh() {
  try { render(await api("/api/state")); } catch (e) { console.error(e); }
}

async function refreshTrust() {
  const [sent, access] = await Promise.all([api("/api/residents/margaret/events"), api("/api/access-log")]);
  document.getElementById("sent").replaceChildren(...(sent.length ? sent : [null]).map(e =>
    e ? el("li", {}, `${e.kind} at ${new Date(e.time).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", timeZone: "America/Edmonton" })}`)
      : el("li", { class: "muted" }, "Nothing yet")));
  document.getElementById("access").replaceChildren(...access.map(a =>
    el("li", {}, `${a.who} ${a.what}, ${new Date(a.time).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" })}`)));
}

(async () => {
  renderNav();
  const { cfg, signedIn } = await setupAuth();
  window.storeKind = cfg.store;
  if (!signedIn) { document.getElementById("signin").style.display = "block"; return; }
  document.getElementById("app").hidden = false;
  document.getElementById("who").replaceChildren(
    cfg.auth0 ? el("button", { class: "btn", onclick: signOut }, "Sign out") : el("span", {}, "Dev mode: sign-in is off"));
  const banners = [];
  if (!cfg.gemini) banners.push("No Gemini key yet, so messages use a template. Add one on the Keys page.");
  if (banners.length) document.getElementById("banner").replaceChildren(el("div", { class: "banner" }, banners.join(" · ")));
  await api("/api/access", { what: "opened the coordinator dashboard" });
  const links = await api("/api/volunteer-links");
  document.getElementById("links").replaceChildren(...links.map(l =>
    el("li", {}, el("a", { href: l.path, target: "_blank" }, l.name), ` (${l.language})`)));
  refresh(); refreshTrust();
  setInterval(refresh, 1000);
  setInterval(refreshTrust, 5000);
})();
