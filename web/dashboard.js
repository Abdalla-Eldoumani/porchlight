// The caregiver console: who needs someone, where they are, and what to do next.
const LEVEL_WORD = { normal: "Normal", watch: "Tight", alert: "Grid alert", emergency: "Emergency" };
const ORDER = { help: 0, alert: 1, visitor: 2, asked: 3, waiting: 4, ok: 5 };
let S = null, city = null, selected = null, pickedByHand = 0, chartDay = null, personKey = "";
const $ = id => document.getElementById(id);
let me = null;   // the signed-in caregiver's Auth0 profile
// The server records Auth0 user ids; show a name instead.
const whoName = id => me && id === me.sub ? "you" : String(id).includes("|") ? "a caregiver" : id;

function eventTime(value) {
  return value ? new Date(value).toLocaleString("en-CA", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Edmonton" }) : "not yet";
}
function countdown(check) {
  const sec = Math.max(0, Math.ceil(check.remaining_seconds));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
const needsSomeone = p => ["help", "alert", "visitor", "asked"].includes(shownStatus(p));

function shortLine(p) {
  const a = p.alert, c = p.box && p.box.manual_check;
  if (p.status === "ok" && c && c.status === "pending") return ["warm", `Check-in sent · ${countdown(c)} left`];
  if (p.status === "ok" && c && c.status === "unanswered") return ["urgent", "Didn't answer the check-in"];
  switch (p.status) {
    case "ok": return ["", `OK at ${p.last_ok}`];
    case "waiting": return ["", `Hasn't checked in yet (by ${p.cutoff})`];
    case "asked": return ["warm", "Asked to press I'm OK"];
    case "help": return ["urgent", `Pressed Help · asking ${a.asking}`];
    case "alert": return ["urgent", `${a.reason} · asking ${a.asking}`];
    case "visitor": return ["warm", `${a.going[0].toUpperCase() + a.going.slice(1)} is going, there by ${a.eta}`];
  }
  return ["", p.status];
}

// ---- roster ------------------------------------------------------------------
function rosterRow(p) {
  const st = shownStatus(p), [tone, line] = shortLine(p);
  return el("button", { class: "row", "aria-current": p.id === selected, onclick: () => choose(p.id) },
    el("span", { class: `g ${st}`, "aria-hidden": "true" }, PIN_SYMBOL[st]),
    el("span", { class: "n" }, p.name, el("small", {}, p.community)),
    el("span", { class: "t" }, p.simulated ? "" : "real box"),
    el("span", { class: `s ${tone}` }, el("span", { class: "sr-only" }, PIN_WORD[st] + ": "), line));
}
let rosterKey = "";
function drawRoster(people) {
  // Redraw only when something changed, so a click never lands on a button that was just replaced.
  const key = JSON.stringify([selected, S.mode, people.map(p => [p.id, shownStatus(p), shortLine(p)])]);
  if (key === rosterKey) return;
  rosterKey = key;
  const urgent = people.filter(needsSomeone), fine = people.filter(p => !needsSomeone(p));
  const parts = [];
  if (urgent.length) parts.push(el("div", { class: "group" }, el("span", {}, "Needs someone"), el("span", {}, String(urgent.length))), ...urgent.map(rosterRow));
  else parts.push(el("div", { class: "calm" }, el("b", {}, "Nobody needs a visit right now."),
    el("p", {}, S.mode === "live" ? "Play back January 13, 2024 to see what happens when the grid nearly fails at −30."
                                  : "Ask someone for a check-in, or press Help on Margaret's box in the demo."),
    S.mode === "live" ? el("button", { class: "btn primary", onclick: () => setMode("replay", 30) }, "Play the January 13 night") : null));
  parts.push(el("div", { class: "group" }, el("span", {}, "Doing fine"), el("span", {}, String(fine.length))), ...fine.map(rosterRow));
  $("people").replaceChildren(...parts);
}

// ---- the selected person -------------------------------------------------------
function drawPerson(p) {
  const a = p.alert, c = p.box && p.box.manual_check, st = shownStatus(p), [tone, line] = shortLine(p);
  const key = JSON.stringify([p.id, p.status, st, a, c && [c.status, c.received_at, c.response_at], p.last_ok_at, p.last_motion_at, p.box_online]);
  const cd = $("cd");
  if (key === personKey) { if (cd && c && c.status === "pending") cd.textContent = countdown(c); return; }
  personKey = key;
  const pending = c && c.status === "pending";
  const actions = [];
  if (a && a.rule === "help" && !a.going) actions.push(el("button", { class: "btn primary", onclick: () => act(a.id, "going") }, "I'm going"));
  if (a) actions.push(el("button", { class: "btn", onclick: () => act(a.id, "cant") }, "Ask the next person"),
                      el("button", { class: "btn", onclick: () => act(a.id, "resolved") }, "Mark resolved"));
  actions.push(el("button", { class: a ? "btn" : "btn primary", disabled: pending, onclick: () => requestCheckin(p.id) }, pending ? "Check-in sent" : "Ask for a check-in"));
  if (c && c.status === "unanswered" && (!a || a.rule !== "help")) actions.push(el("button", { class: "btn danger", onclick: () => requestAssistance(p.id) }, "Send someone"));
  $("person").replaceChildren(...[
    el("div", { class: "who" }, el("h2", {}, p.name), el("p", {}, `${p.community} · ${p.simulated ? "simulated home" : "real box"}`)),
    el("div", { class: `state ${tone}` },
      el("div", { class: `status ${st}` }, PIN_WORD[st]),
      el("p", {}, pending ? el("span", {}, "Check-in sent · ", el("b", { id: "cd" }, countdown(c)), ` left · ${c.received_at ? "the box has it" : "waiting for the box"}`) : line)),
    el("dl", { class: "facts" },
      el("dt", {}, "Last I'm OK"), el("dd", {}, eventTime(p.last_ok_at)),
      el("dt", {}, "Last moved"), el("dd", {}, eventTime(p.last_motion_at)),
      el("dt", {}, "Looked after by"), el("dd", {}, p.assigned_responder),
      el("dt", {}, "Box"), el("dd", {}, p.simulated ? "Simulated" : p.box_online ? "Online" : "Offline"),
      c ? el("dt", {}, "Check-in") : null, c ? el("dd", {}, `asked ${eventTime(c.requested_at)} by ${whoName(c.requested_by)}`) : null),
    a && a.message ? el("blockquote", { class: "msg", dir: "auto" }, a.message,
      el("small", {}, a.message_source === "gemini" ? "Worded by Gemini from the rule's facts" : "From a template")) : null,
    el("div", { class: "actions" }, ...actions),
    a ? el("p", { class: "next" }, "Next on the list: " + (a.chain.slice(a.step + 1).join(" → ") || "nobody")) : null,
    el("p", { id: "action-status", role: "status" })].filter(Boolean));
}

function choose(id) { selected = id; pickedByHand = Date.now(); personKey = ""; render(S); city.select(id); }

// ---- the whole screen ------------------------------------------------------------
function stat(label, value, cls) { return el("div", { class: "cond" }, el("b", { class: cls || "" }, value), el("span", {}, label)); }

function render(s) {
  S = s;
  $("clock").textContent = s.clock;
  $("mode").textContent = s.mode === "replay" ? `REPLAY · ${s.speed ? s.speed + "×" : "PAUSED"}` : "LIVE";
  const c = s.conditions;
  $("stats").replaceChildren(
    stat("Outside", c.temp_c == null ? "–" : `${Math.round(c.temp_c)} °C`),
    stat("Alberta grid", LEVEL_WORD[c.level] || c.level, `level ${c.level}`),
    stat("Demand", c.ail_mw == null ? "–" : `${Math.round(c.ail_mw).toLocaleString()} MW`),
    c.price != null ? stat("Pool price", `$${c.price.toFixed(2)}`) : stat("Supply cushion", c.cushion_mw == null ? "–" : `${Math.round(c.cushion_mw)} MW`));
  document.querySelectorAll(".speed").forEach(b => b.setAttribute("aria-pressed", s.mode === "replay" && Number(b.dataset.speed) === s.speed));
  city.update(s.residents);
  const people = [...s.residents].sort((x, y) => ORDER[shownStatus(x)] - ORDER[shownStatus(y)]);
  // Follow the most urgent person unless the caregiver picked someone in the last 30 seconds.
  if (!selected || (Date.now() - pickedByHand > 30000 && needsSomeone(people[0]) && people[0].id !== selected)) {
    selected = people[0].id; city.select(selected);
  }
  drawRoster(people);
  drawPerson(people.find(p => p.id === selected) || people[0]);
  $("feed").replaceChildren(...s.feed.map(f =>
    el("li", {}, el("time", {}, new Date(f.t).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", timeZone: "America/Edmonton" })),
      el("span", { class: f.kind }, f.text))));
  if (c.error) $("banner").replaceChildren(el("div", { class: "banner" }, "Live data: " + c.error));
  else if ($("banner").textContent.startsWith("Live data")) $("banner").replaceChildren();
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
  for (let h = 0; h <= 24; h += 6) parts.push(`<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${H - B}" stroke="#1c212b"/><text x="${x(h)}" y="${H - 8}" text-anchor="middle">${h === 24 ? "" : (h % 12 || 12) + (h < 12 ? " am" : " pm")}</text>`);
  if (g.rows.length) {
    parts.push(`<path d="${path(g.rows, "price", yP)}" fill="none" stroke="#8fb8e8" stroke-width="1.5" stroke-dasharray="4 3"/>`);
    parts.push(`<path d="${path(g.rows, "ail_mw", yA)}" fill="none" stroke="#f2b544" stroke-width="2.5"/>`);
    parts.push(`<text x="${L - 6}" y="${yA(hi - 200)}" text-anchor="end">${Math.round(hi - 200).toLocaleString()}</text><text x="${L - 6}" y="${yA(lo + 200)}" text-anchor="end">${Math.round(lo + 200).toLocaleString()}</text>`);
    parts.push(`<text x="${W - R + 6}" y="${yP(1000) + 4}">$1000</text><text x="${W - R + 6}" y="${yP(0)}">$0</text>`);
  }
  g.events.forEach((e, i) => {
    const ex = x(hourOf(e.time));
    parts.push(`<g><title>${e.text}</title><line x1="${ex}" x2="${ex}" y1="${T}" y2="${H - B}" stroke="${e.level === "emergency" ? "#ff7262" : "#f29a52"}" stroke-width="1"/><circle cx="${ex}" cy="${T - 6}" r="5" fill="${e.level === "emergency" ? "#ff7262" : "#f29a52"}"/><text x="${ex}" y="${T - 3}" text-anchor="middle" style="fill:#0b0d12;font-size:8px;font-weight:700">${i + 1}</text></g>`);
  });
  parts.push(`<line id="nowline" y1="${T}" y2="${H - B}" stroke="#eceef2" stroke-width="1.5"/>`);
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
async function caregiverAction(path, body, message) {
  pickedByHand = Date.now();   // stay on this person after acting, so the caregiver sees the result
  try {
    await api(path, body);
    personKey = "";
    await refresh();
    const out = $("action-status"); if (out) { out.className = ""; out.textContent = message; }
  } catch (e) { const out = $("action-status"); if (out) { out.className = "err"; out.textContent = "That didn't go through: " + e.message; } }
}
async function act(id, action) { return caregiverAction(`/api/alerts/${id}/${action}`, {}, { going: "Marked as going. They'll see a heart on their box.", cant: "Asked the next person.", resolved: "Resolved." }[action]); }
async function requestCheckin(rid) { return caregiverAction(`/api/residents/${rid}/check-in`, {}, "Check-in sent. Their box is asking now."); }
async function requestAssistance(rid) { return caregiverAction(`/api/residents/${rid}/press`, { kind: "help" }, "Asked the first person on their list."); }
async function setMode(mode, speed) { await api("/api/mode", { mode, speed }); chartDay = null; refresh(); }
async function setSpeed(speed) { await api("/api/speed", { speed }); refresh(); }

async function refresh() {
  try { render(await api("/api/state")); }
  catch (e) { console.error(e); $("banner").replaceChildren(el("div", { class: "banner error" }, e.message.startsWith("401") ? "The server didn't accept your sign-in: " + e.message : "Can't reach the server. Is it still running?")); }
}

async function refreshTrust() {
  try {
    const [sent, access] = await Promise.all([api("/api/residents/margaret/events"), api("/api/access-log")]);
    $("sent").replaceChildren(...(sent.length ? sent : [null]).slice(0, 8).map(e =>
      e ? el("li", {}, `${e.kind} at ${new Date(e.time).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", timeZone: "America/Edmonton" })}`)
        : el("li", { class: "muted" }, "Nothing yet")));
    const seen = new Set();   // the log repeats the same view every few seconds; show each kind once
    $("access").replaceChildren(...access.filter(a => !seen.has(a.who + a.what) && seen.add(a.who + a.what)).slice(0, 6).map(a =>
      el("li", {}, `${whoName(a.who)[0].toUpperCase() + whoName(a.who).slice(1)} ${a.what}, ${new Date(a.time).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" })}`)));
  } catch { /* the banner from refresh() already says what's wrong */ }
}

function showGate(error) {
  $("loading").hidden = true;
  $("signin").hidden = false;
  if (error) $("signin-error").textContent = error;
}

(async () => {
  renderNav();
  let cfg, signedIn;
  try { ({ cfg, signedIn } = await setupAuth()); }
  catch (e) { return showGate("Sign-in didn't finish: " + e.message); }
  window.storeKind = cfg.store;
  if (!signedIn) return showGate();
  try { await api("/api/access", { what: "opened the caregiver console" }); }
  catch (e) { return showGate("The server didn't accept your sign-in: " + e.message); }
  $("loading").hidden = true;
  $("app").hidden = false;
  me = cfg.auth0 ? await auth0Client.getUser() : null;
  $("who").replaceChildren(cfg.auth0 ? el("span", {}, (me && (me.name || me.email)) || "Signed in", " · ", el("a", { href: "#", onclick: e => { e.preventDefault(); signOut(); } }, "Sign out")) : "Sign-in is off");
  $("services").innerHTML = serviceChips(cfg);
  if (!cfg.gemini) $("banner").replaceChildren(el("div", { class: "banner" }, "No Gemini key yet, so messages use a template. Add one on the Keys page."));
  city = makeMap("map", { onSelect: choose });
  const links = await api("/api/volunteer-links");
  $("links").replaceChildren(...links.map(l => el("li", {}, el("a", { href: l.path, target: "_blank" }, l.name), ` · ${{ en: "English", ar: "Arabic", zh: "Chinese", fr: "French" }[l.language] || l.language}`)));
  await refresh(); refreshTrust();
  setInterval(refresh, 1000);
  setInterval(refreshTrust, 5000);
})();
