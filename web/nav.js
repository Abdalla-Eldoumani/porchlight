// Brand, top bar and the two reading settings (bigger text, high contrast),
// shared by every page. The settings are applied before the page draws so
// there's no flash, and they're remembered in this browser when it allows.
const SLOGAN = "A light left on for every neighbour.";
(function applyReadingSettings() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem("porchlight-reading") || "{}"); } catch {}
  document.documentElement.classList.toggle("big-text", !!s.big);
  document.documentElement.classList.toggle("contrast", !!s.contrast);
})();

function toggleReading(key) {
  let s = {};
  try { s = JSON.parse(localStorage.getItem("porchlight-reading") || "{}"); } catch {}
  s[key] = !s[key];
  try { localStorage.setItem("porchlight-reading", JSON.stringify(s)); } catch {}
  document.documentElement.classList.toggle(key === "big" ? "big-text" : "contrast", s[key]);
  document.querySelectorAll(`[data-reading="${key}"]`).forEach(b => b.setAttribute("aria-pressed", s[key]));
}

// The mark: a house with its porch light on (mark.svg, also the favicon).
// The wordmark dots its i with the same light.
const MARK = `<img class="mark" src="mark.svg" alt="" width="32" height="32">`;
const WORDMARK = `<span class="wordmark" aria-hidden="true">porchl<span class="i">i</span>ght</span>`;

function brandHTML() {
  return `<a class="brand" href="/" aria-label="Porchlight, back to the start">${MARK}${WORDMARK}</a>`;
}

function readingButtons() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem("porchlight-reading") || "{}"); } catch {}
  return `<button class="readset" data-reading="big" aria-pressed="${!!s.big}" onclick="toggleReading('big')" title="Bigger text"><span aria-hidden="true">A<span>A</span></span><span class="sr-only">Bigger text</span></button>
      <button class="readset" data-reading="contrast" aria-pressed="${!!s.contrast}" onclick="toggleReading('contrast')" title="High contrast"><svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 1.5a6.5 6.5 0 0 1 0 13z" fill="currentColor"/></svg><span class="sr-only">High contrast</span></button>`;
}

async function renderNav() {
  const here = location.pathname.split("/").pop() || "index.html";
  const pages = [["index.html", "Demo"], ["pitch.html", "Pitch"], ["about.html", "How it works"],
                 ["dashboard.html", "Coordinator"], ["box.html", "Box"], ["setup.html", "Keys"]];
  const nav = document.getElementById("nav");
  nav.className = "nav";
  nav.setAttribute("aria-label", "Main");
  nav.innerHTML = `<a class="skip" href="#main">Skip to content</a>${brandHTML()}
    <div class="links">${pages.map(([href, name]) =>
      `<a href="${href}"${href === here ? ' aria-current="page"' : ""}>${name}</a>`).join("")}</div>
    <div class="right">
      <span id="chips" class="chips"></span>
      ${readingButtons()}
    </div>`;
  try {
    const c = await (await fetch("/api/config")).json();
    const chip = (on, label, title) => `<a class="chip ${on ? "on" : ""}" href="setup.html" title="${title}">${label}</a>`;
    document.getElementById("chips").innerHTML =
      chip(c.gemini, "Gemini", c.gemini ? "Messages are written by Gemini" : "Add a Gemini key on the Keys page") +
      chip(c.store !== "memory", "Tiger Data", c.store === "memory" ? "Data is kept in memory" : "Stored in " + c.store) +
      chip(c.aeso_key, "AESO live", c.aeso_key ? "Live grid data is available" : "Add an AESO key for live mode") +
      chip(!!c.auth0, "Auth0", c.auth0 ? "Coordinator sign-in is on" : "Sign-in is off (fine for the demo)");
    return c;
  } catch { return null; }
}
