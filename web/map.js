// The Calgary map shared by the demo and the caregiver console. Real streets
// from OpenStreetMap, darkened in CSS to match the page. Each home is a pin
// with a symbol and a word for its status, so it never depends on colour alone.
const PIN_SYMBOL = { ok: "✓", asked: "?", alert: "!", help: "!", visitor: "→", waiting: "·" };
const PIN_WORD = { ok: "OK", waiting: "Not yet", asked: "Asked", alert: "No answer", help: "Help", visitor: "Help is coming" };

// A pending or missed check-in shows on the pin even though the rules still call the person OK.
function shownStatus(r) {
  const c = r.box && r.box.manual_check;
  if (r.status === "ok" && c && c.status === "pending") return "asked";
  if (r.status === "ok" && c && c.status === "unanswered") return "alert";
  return r.status;
}

function makeMap(id, { onSelect, onAsk } = {}) {
  const map = L.map(id, { zoomControl: false, scrollWheelZoom: false });
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  map.setView([51.05, -114.06], 11);
  map.on("click", () => map.scrollWheelZoom.enable());
  map.on("mouseout", () => map.scrollWheelZoom.disable());
  const pins = {};
  let residents = [], selected = null;

  // A label goes above its pin when another home sits just below it, so names don't overlap.
  const above = r => residents.some(o => o !== r && o.lat < r.lat && r.lat - o.lat < 0.03 && Math.abs(o.lon - r.lon) < 0.05);
  const pinHTML = r => {
    const st = shownStatus(r), quiet = st === "ok" || st === "waiting";
    return `<div class="pin ${st}${above(r) ? " above" : ""}${r.id === selected ? " sel" : ""}"><span class="ring"></span><span class="dot">${PIN_SYMBOL[st] || ""}</span>
      <span class="tag"><b>${r.name}</b>${quiet ? "" : `<small>${PIN_WORD[st]}</small>`}</span></div>`;
  };
  const popupHTML = r => {
    const c = r.box && r.box.manual_check, pending = c && c.status === "pending";
    const note = pending ? `<p class="pop-note asked">Check-in sent · ${Math.ceil(c.remaining_seconds / 60)} min left</p>`
      : c && c.status === "confirmed" ? `<p class="pop-note ok">Answered the check-in</p>`
      : c && c.status === "unanswered" ? `<p class="pop-note alert">No answer to the check-in</p>` : "";
    return `<div class="pop"><b>${r.name}</b><span>${r.community}${r.simulated ? "" : " · real box"}</span>
      <p class="status ${shownStatus(r)}">${PIN_WORD[shownStatus(r)]}</p>${note}
      ${onAsk ? `<button class="btn primary" ${pending ? "disabled" : ""} data-ask="${r.id}">${pending ? "Waiting for them" : "Ask for a check-in"}</button>` : ""}</div>`;
  };
  map.on("popupopen", e => {
    const b = e.popup.getElement().querySelector("[data-ask]");
    if (b) b.addEventListener("click", () => onAsk(b.dataset.ask));
  });

  function update(list) {
    if (!list.length) return;
    const fresh = !residents.length;
    residents = list;
    list.forEach(r => {
      const html = pinHTML(r);
      const icon = () => L.divIcon({ className: "", html, iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -16] });
      let p = pins[r.id];
      if (!p) {
        p = pins[r.id] = L.marker([r.lat, r.lon], { icon: icon(), keyboard: true, title: `${r.name}, ${r.community}`, riseOnHover: true }).addTo(map);
        p._html = html;
        if (onAsk) p.bindPopup("", { className: "pop-wrap", maxWidth: 240, closeButton: false });
        p.on("click", () => onSelect && onSelect(r.id));
      }
      if (p._html !== html) { p._html = html; p.setIcon(icon()); }
      p.setZIndexOffset(["help", "alert", "asked"].includes(shownStatus(r)) ? 1000 : 0);
      if (onAsk) { const pop = popupHTML(r); if (p._pop !== pop) { p._pop = pop; p.setPopupContent(pop); } }
    });
    if (fresh) map.fitBounds(L.latLngBounds(list.map(r => [r.lat, r.lon])).pad(0.15));
  }
  function select(id) {
    selected = id;
    if (!residents.length) return;
    update(residents);
    const r = residents.find(x => x.id === id);
    if (r) map.panTo([r.lat, r.lon], { animate: true });
  }
  return { update, select, map };
}
