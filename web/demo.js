// The demo screen: Margaret's box, a map of Calgary, a volunteer's phone,
// and one sentence saying what is happening now. Everything comes from the
// same API the real box, the coordinator and volunteers use.
const COLOR = { ok: "var(--mint)", asked: "var(--amber)", alert: "var(--coral)", help: "var(--coral)",
                visitor: "var(--amber)", waiting: "var(--faint)" };
const LEVEL = { normal: "Normal", watch: "Tight", alert: "Grid alert", emergency: "Emergency" };
let S = null, links = [], picked = null, pickedByHand = 0, lastBoxBuzz = null, lastTaskCount = 0, chartDay = null, chart = null;

const $ = id => document.getElementById(id);
const tz = { timeZone: "America/Edmonton" };
const clockText = iso => new Date(iso).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit", ...tz });

// ---- the box ----------------------------------------------------------------
const dots = Array.from({ length: 104 }, () => $("matrix").appendChild(document.createElement("i")));
function drawBox(b) {
  (PATTERNS[b.display] || PATTERNS.idle).join("").split("").forEach((c, i) => dots[i].classList.toggle("on", c === "#"));
  $("boxline").textContent = b.text;
  if (lastBoxBuzz !== null && b.buzz > lastBoxBuzz) shake($("box"));
  lastBoxBuzz = b.buzz;
}
function shake(node) { node.classList.remove("buzz"); void node.offsetWidth; node.classList.add("buzz"); }
async function press(kind) {
  if (kind === "ok") drawBox({ display: "ok", text: "", buzz: lastBoxBuzz });
  drawBox(await api("/api/residents/margaret/press", { kind }));
  refresh();
}

// ---- the map ------------------------------------------------------------------
// Real Calgary streets from OpenStreetMap, darkened with a CSS filter to match the page. Each home is a pin with a
// symbol and a word for its status, so it never depends on colour alone.
const SYMBOL = { ok: "✓", asked: "?", alert: "!", help: "!!", visitor: "♥", waiting: "…" };
let map = null;
const pins = {};
function drawMap() {
  map = L.map("map", { zoomControl: false, scrollWheelZoom: false, attributionControl: true });
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  map.setView([51.06, -114.06], 11);
  map.on("focus click", () => map.scrollWheelZoom.enable());
  map.on("blur mouseout", () => map.scrollWheelZoom.disable());
}
// A label goes above its pin when another home sits just below it, so names don't overlap.
function labelAbove(r) {
  return S.residents.some(o => o !== r && o.lat < r.lat && r.lat - o.lat < 0.03 && Math.abs(o.lon - r.lon) < 0.05);
}
function shown(r) {
  const c = r.box && r.box.manual_check;
  if (r.status === "ok" && c && c.status === "pending") return "asked";
  if (r.status === "ok" && c && c.status === "unanswered") return "alert";
  return r.status;
}
function pinHTML(r) {
  const st = shown(r), quiet = st === "ok" || st === "waiting";
  return `<div class="pin ${st}${labelAbove(r) ? " above" : ""}"><span class="ring"></span><span class="dot">${SYMBOL[st] || ""}</span>
    <span class="tag"><b>${r.name}</b>${quiet ? "" : `<small>${statusLabel(st)}</small>`}</span></div>`;
}
function statusLabel(st) {
  return { ok: "OK", waiting: "not yet", asked: "asked", alert: "no answer", help: "Help", visitor: "someone's coming" }[st] || st;
}
function popupHTML(r) {
  const c = r.box && r.box.manual_check;
  const check = c && c.status === "pending" ? `<p class="pop-note">Check-in sent, ${Math.ceil(c.remaining_seconds / 60)} min left</p>`
    : c && c.status === "confirmed" ? `<p class="pop-note ok">Answered the check-in</p>`
    : c && c.status === "unanswered" ? `<p class="pop-note warn">No answer to the check-in</p>` : "";
  return `<div class="pop"><h3>${r.name}</h3><p class="muted">${r.community} · ${r.simulated ? "simulated" : "real box"}</p>
    <p class="status ${r.status}">${statusWords(r)}</p>
    <p class="muted small">Last I'm OK: ${r.last_ok || "not yet"}${r.last_motion ? ` · moved ${r.last_motion}` : ""}</p>${check}
    <button class="btn primary" ${c && c.status === "pending" ? "disabled" : ""} onclick="askCheckin('${r.id}')">Ask for a check-in</button></div>`;
}
async function askCheckin(rid) {
  try { await api(`/api/residents/${rid}/check-in`, {}); } catch (e) { $("hint").textContent = "Couldn't send the check-in: " + e.message; }
  refresh();
}
function drawHomes(residents) {
  if (!map) return;
  const fresh = !Object.keys(pins).length;
  residents.forEach(r => {
    const html = pinHTML(r);
    const icon = () => L.divIcon({ className: "", html, iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -14] });
    let p = pins[r.id];
    if (!p) {
      p = pins[r.id] = L.marker([r.lat, r.lon], { icon: icon(), keyboard: true, title: `${r.name}, ${r.community}`, riseOnHover: true }).addTo(map);
      p.bindPopup("", { className: "dark-pop", maxWidth: 260 });
      p._html = html;
    }
    if (p._html !== html) { p._html = html; p.setIcon(icon()); }
    p.setZIndexOffset(["help", "alert", "asked"].includes(shown(r)) ? 1000 : 0);
    const pop = popupHTML(r);
    if (p._pop !== pop) { p._pop = pop; p.setPopupContent(pop); }
  });
  if (fresh) map.fitBounds(L.latLngBounds(residents.map(r => [r.lat, r.lon])).pad(0.12));
}
function statusWords(r) {
  const a = r.alert;
  return { ok: `OK at ${r.last_ok}`, waiting: "not checked in yet", asked: "asked to press I'm OK",
           help: `pressed Help, asking ${a && a.asking}`, alert: `no answer, asking ${a && a.asking}`,
           visitor: `${a && a.going} is coming` }[r.status];
}

// ---- the phone ------------------------------------------------------------------
function tasksFor(vid) {
  const v = links.find(l => l.id === vid);
  return S.residents.filter(r => r.alert && (r.alert.asking_id === vid && !r.alert.going || r.alert.going === v.name)).length;
}
function drawWho() {
  $("who").replaceChildren(...links.map(l => {
    const n = tasksFor(l.id);
    return el("button", { "aria-pressed": l.id === picked, onclick: () => { picked = l.id; pickedByHand = Date.now(); drawWho(); drawPhone(); } },
      l.name, n ? el("span", { class: "n" }, String(n)) : null);
  }));
}
// The request the screen is about: a help call first, then the newest one.
// The sentence and the phone both follow it, so they always agree.
function focus() {
  const open = S.residents.filter(r => r.alert && !r.alert.going)
                          .sort((a, b) => (b.alert.rule === "help") - (a.alert.rule === "help") || b.alert.id - a.alert.id);
  return open[0];
}
function autoPick() {
  if (Date.now() - pickedByHand < 20000) return;      // someone just chose a phone by hand
  const r = focus();
  if (r && r.alert.asking_id !== "coordinator") picked = r.alert.asking_id;
}
let lastTaskKey = "";
async function drawPhone() {
  const v = links.find(l => l.id === picked);
  if (!v) return;
  $("phonewho").textContent = `${v.name}${v.language !== "en" ? " · reads " + ({ ar: "Arabic", zh: "Chinese", fr: "French" }[v.language] || v.language) : ""}`;
  const res = await fetch(`/api/v/${v.token}`);
  if (!res.ok) return;
  const data = await res.json();
  const key = picked + data.tasks.map(t => `${t.id}:${t.mine}:${t.message ? 1 : 0}`).join(",");
  if (key === lastTaskKey) return;                     // don't redraw under a thumb
  if (data.tasks.length > lastTaskCount && lastTaskKey.startsWith(picked)) shake($("phone"));
  lastTaskKey = key; lastTaskCount = data.tasks.length;
  $("tasks").replaceChildren(...(data.tasks.length ? data.tasks.map(t => task(v, t))
    : [el("div", { class: "empty" }, `Nothing for ${v.name} right now.`, el("br"), el("span", { class: "small" }, "Requests show up here."))]));
}
const eta = {};
function task(v, t) {
  const act = async action => {
    await fetch(`/api/v/${v.token}/alerts/${t.id}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, eta_min: eta[t.id] || 15 }) });
    lastTaskKey = ""; refresh();
  };
  const card = el("article", { class: `task ${t.rule === "help" ? "help" : ""}` },
    el("div", { class: `status ${t.rule === "help" ? "help" : "alert"} small` }, t.reason),
    el("h3", {}, t.name, " ", el("span", { class: "small muted" }, t.community)),
    t.message ? el("p", { dir: "auto" }, t.message) : el("p", { class: "muted small" }, "Writing the message…"));
  if (t.mine) {
    card.append(el("p", {}, "You'll be there by ", el("b", {}, t.eta), "."), el("p", { class: "address" }, t.address),
      el("button", { class: "btn primary big", onclick: () => act("resolved") }, "I'm with them, all good"));
  } else {
    const pick = el("div", { class: "eta", role: "group", "aria-label": "How soon can you get there?" },
      ...[10, 15, 30].map(m => el("button", { class: "btn", "aria-pressed": (eta[t.id] || 15) === m,
        onclick: e => { eta[t.id] = m; pick.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b === e.target)); } }, `${m} min`)));
    card.append(pick, el("button", { class: "btn primary big", onclick: () => act("going") }, "I'm going"),
      el("button", { class: "btn big", onclick: () => act("cant") }, "I can't, ask the next person"));
  }
  return card;
}

// ---- the story: which step, and one plain sentence ---------------------------------
function story() {
  const R = S.residents, c = S.conditions;
  const waveSeen = S.feed.some(f => f.kind === "wave");
  const open = R.filter(r => r.alert && !r.alert.going);
  const coming = R.filter(r => r.status === "visitor");
  const asked = R.filter(r => r.status === "asked");
  const me = R.find(r => r.id === "margaret");
  const help = open.find(r => r.alert.rule === "help");
  let step = 0, text = "", hint = "";
  const temp = c.temp_c == null ? "" : `${Math.round(c.temp_c)} °C`;
  if (open.length) {
    step = 3;
    const r = focus(), who = r.alert.asking;
    if (help) text = `Margaret pressed Help. ${who === "the coordinator" ? "Nobody else answered, so the coordinator" : who} is being asked right now. The replay has slowed to real time.`;
    else if (r.alert.asking_id === "coordinator") text = `Nobody answered for ${r.name}, so it reached the coordinator's screen.`;
    else text = `${r.name} hasn't answered. ${who}'s phone is buzzing${r.alert.step ? ", because the first person didn't answer" : ""}.`;
    hint = r.alert.asking_id === "coordinator" ? "Open Coordinator in the top bar to see it" : `Answer on ${who}'s phone  →`;
  } else if (coming.length) {
    step = 4;
    const r = coming[0];
    text = `${r.alert.going} is on the way to ${r.name}, there by ${r.alert.eta}. ${r.name}'s box is showing a heart, so ${r.name} knows someone is coming.`;
    hint = me.status === "visitor" ? "When the volunteer arrives, tap “I'm with them”" : "←  Try Help on Margaret's box to see an emergency";
  } else if (asked.length) {
    step = 1;
    text = `3:30 PM: the AESO declared a grid emergency. It's ${temp}. Every box in Calgary is asking: are you OK?`;
    hint = me.status === "asked" ? "←  Press I'm OK on Margaret's box" : `Waiting for ${asked.map(r => r.name).join(" and ")} to answer`;
  } else if (waveSeen) {
    step = 2;
    const ok = R.filter(r => r.status === "ok").length;
    text = `Everyone answered: ${ok} of ${R.length} neighbours are OK. Anyone who doesn't answer within 30 minutes gets a neighbour at the door.`;
    hint = "←  Press Help on Margaret's box to see an emergency";
  } else {
    step = 0;
    const price = c.price != null ? ` Power costs $${c.price.toFixed(2)} a megawatt-hour, near the $999.99 cap.` : "";
    text = c.level === "normal" ? `It's ${temp} in Calgary. The grid is fine, so nobody is bothered.`
                                : `It's ${temp} in Calgary.${price} The grid is close to running out.`;
    hint = S.mode === "replay" ? "The AESO's alert comes at 3:30 PM. Press Skip ahead to get there" : "";
  }
  if (!open.length && S.mode === "replay" && S.speed === 1) hint = "The replay is at 1× since the help call. Press 30× to speed the day back up";
  $("steps").querySelectorAll("li").forEach((li, i) => li.className = i < step ? "done" : i === step ? "now" : "");
  $("narration").textContent = text;
  $("hint").textContent = hint;
  $("press-ok").classList.toggle("nudge", me.status === "asked");
}

// ---- the grid band ---------------------------------------------------------------------
async function drawChart(day) {
  const g = await api(`/api/grid/day/${day}`);
  const svg = $("chart"), W = 640, H = 210, L = 64, R = 46, T = 16, B = 24;
  const hourOf = t => { const d = new Date(t); return Number(d.toLocaleString("en-CA", { hour: "numeric", hour12: false, ...tz })) % 24 + d.getMinutes() / 60; };
  const x = h => L + (h / 24) * (W - L - R);
  const ail = g.rows.map(r => r.ail_mw), lo = Math.min(...ail) - 150, hi = Math.max(...ail) + 150;
  const yA = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B), yP = v => T + (1 - v / 1000) * (H - T - B);
  const path = (key, y) => g.rows.map((r, i) => `${i ? "L" : "M"}${x(hourOf(r.time) + 0.5).toFixed(1)},${y(r[key]).toFixed(1)}`).join("");
  const parts = [];
  for (let h = 0; h <= 24; h += 3) parts.push(`<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${H - B}" stroke="#202a43"/>${h < 24 ? `<text x="${x(h)}" y="${H - 6}" text-anchor="middle">${(h % 12 || 12) + (h < 12 ? "a" : "p")}</text>` : ""}`);
  if (g.rows.length) {
    parts.push(`<path d="${path("price", yP)} L${x(24)},${yP(0)} L${x(0.5)},${yP(0)}Z" fill="rgba(99,198,255,0.08)"/>`);
    parts.push(`<path d="${path("price", yP)}" fill="none" stroke="#63c6ff" stroke-width="1.6" stroke-opacity="0.7"/>`);
    parts.push(`<path d="${path("ail_mw", yA)}" fill="none" stroke="#ffb547" stroke-width="3" stroke-linejoin="round"/>`);
    parts.push(`<text x="${L - 6}" y="${yA(hi - 150) + 4}" text-anchor="end">${Math.round((hi - 150) / 100) / 10}k MW</text>`);
    parts.push(`<text x="${W - R + 6}" y="${yP(1000) + 4}">$1000</text><text x="${W - R + 6}" y="${yP(0)}">$0</text>`);
  }
  g.events.forEach((e, i) => {
    const ex = x(hourOf(e.time)), col = e.level === "emergency" ? "#ff5d78" : "#ff9a4d";
    parts.push(`<g><title>${e.text}</title><line x1="${ex}" x2="${ex}" y1="${T}" y2="${H - B}" stroke="${col}" stroke-opacity="0.7"/></g>`);
  });
  parts.push(`<rect id="past" x="${L}" y="${T}" height="${H - T - B}" width="0" fill="rgba(255,255,255,0.035)"/><line id="nowline" y1="${T - 4}" y2="${H - B}" stroke="#f1f3f9" stroke-width="2"/>`);
  svg.innerHTML = parts.join("");
  chart = { x, hourOf, L, events: g.events };
  $("chartnote").innerHTML = g.rows.length
    ? `<span style="color:var(--amber)">━</span> demand  <span style="color:var(--sky)">━</span> pool price · sources: AESO pool price report, Market Surveillance Administrator, Environment Canada · stored in ${g.store}`
    : "No readings stored for this day yet.";
}
function moveChart(now) {
  if (!chart) return;
  const nx = chart.x(chart.hourOf(now));
  $("nowline").setAttribute("x1", nx); $("nowline").setAttribute("x2", nx);
  $("past").setAttribute("width", Math.max(0, nx - chart.L));
  $("events").replaceChildren(...chart.events.map(e =>
    el("li", { class: new Date(e.time) <= new Date(now) ? "past" : "" }, el("time", {}, clockText(e.time)), el("span", {}, e.text))));
}

// ---- the loop ------------------------------------------------------------------------
function readings(c) {
  const r = (label, value, cls) => el("div", { class: `reading ${cls || ""}` }, el("b", { class: cls && cls.startsWith("level") ? cls : "" }, value), el("span", {}, label));
  return [r("Outside", c.temp_c == null ? "–" : `${Math.round(c.temp_c)}°C`, "cold"),
          r("Alberta's grid", LEVEL[c.level] || c.level, `level ${c.level}`),
          r("Demand", c.ail_mw == null ? "–" : `${(c.ail_mw / 1000).toFixed(1)}k MW`),
          c.price != null ? r("Pool price", `$${c.price.toFixed(2)}`) : r("Supply cushion", c.cushion_mw == null ? "–" : `${Math.round(c.cushion_mw)} MW`)];
}

async function refresh() {
  try { S = await api("/api/state"); } catch (e) { $("narration").textContent = "Can't reach the server. Is it still running?"; return; }
  $("date").textContent = S.date;
  $("time").textContent = S.time;
  $("mode").textContent = S.mode === "replay" ? (S.speed ? `replay at ${S.speed}×` : "paused") : "live";
  $("readings").replaceChildren(...readings(S.conditions));
  document.querySelectorAll("#speeds button").forEach(b => b.setAttribute("aria-pressed", S.mode === "replay" && Number(b.dataset.speed) === S.speed));
  const me = S.residents.find(r => r.id === "margaret");
  drawBox(me.box);
  $("online").innerHTML = me.box_online ? '<span class="chip on">Real box connected</span>' : '<span class="small muted">On-screen box. The real Arduino uses the same API.</span>';
  drawHomes(S.residents);
  const ok = S.residents.filter(r => r.status === "ok").length;
  $("answered").textContent = `${ok} of ${S.residents.length} OK`;
  story();
  autoPick();
  drawWho();
  drawPhone();
  const day = S.now.slice(0, 10);
  if (day !== chartDay) { chartDay = day; await drawChart(day); }
  moveChart(S.now);
  $("lastfeed").textContent = S.feed[0] ? `Latest: ${S.feed[0].text}` : "";
}

async function setSpeed(speed) { await api("/api/speed", { speed }); refresh(); }
async function restart() { await api("/api/mode", { mode: "replay", speed: 30 }); lastTaskKey = ""; picked = links[0] && links[0].id; refresh(); }
async function skip() {
  try { await api("/api/skip", {}); } catch { /* live mode: nothing to skip */ }
  refresh();
}
function closeIntro() { $("intro").hidden = true; try { sessionStorage.setItem("porchlight-intro", "1"); } catch {} }
async function begin() { closeIntro(); await restart(); }

document.querySelectorAll("#speeds button").forEach(b => b.addEventListener("click", () => setSpeed(Number(b.dataset.speed))));

(async () => {
  renderNav();
  const { cfg, signedIn } = await setupAuth();
  if (!signedIn) { $("narration").textContent = "Sign in as a coordinator to run the demo."; $("hint").replaceChildren(el("button", { class: "btn primary", onclick: signIn }, "Sign in")); return; }
  let seen = false;
  try { seen = sessionStorage.getItem("porchlight-intro") === "1"; } catch {}
  $("intro").hidden = seen;
  drawMap();
  links = await api("/api/volunteer-links");
  picked = links[0] && links[0].id;
  refresh();
  setInterval(refresh, 1000);
})();
