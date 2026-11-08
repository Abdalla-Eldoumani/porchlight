// Coordinator API calls. With Auth0 configured, every call carries the
// coordinator's access token; without it the server runs in dev mode.
let auth0Client = null;

async function setupAuth() {
  const cfg = await (await fetch("/api/config")).json();
  if (!cfg.auth0) return { cfg, signedIn: true };
  auth0Client = await auth0.createAuth0Client({
    domain: cfg.auth0.domain,
    clientId: cfg.auth0.clientId,
    authorizationParams: { audience: cfg.auth0.audience, redirect_uri: location.origin + location.pathname },
  });
  if (location.search.includes("code=") && location.search.includes("state=")) {
    await auth0Client.handleRedirectCallback();
    history.replaceState({}, "", location.pathname);
  }
  return { cfg, signedIn: await auth0Client.isAuthenticated() };
}

function signIn() { return auth0Client.loginWithRedirect(); }
function signOut() { return auth0Client.logout({ logoutParams: { returnTo: location.origin + location.pathname } }); }

async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (auth0Client) headers.Authorization = "Bearer " + (await auth0Client.getTokenSilently());
  const res = await fetch(path, body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}
