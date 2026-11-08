"""Coordinator login through Auth0. The dashboard gets an access token from
Auth0 and sends it as a Bearer token; we check its signature, audience and
issuer here. With no Auth0 domain set the server runs open (dev mode)."""
import httpx
import jwt
from fastapi import Header, HTTPException

from . import settings

_keys = {}   # domain -> {kid: public key}, fetched once and again only for a new kid


def _signing_key(domain, token):
    # httpx carries its own CA bundle; PyJWKClient's urllib fetch fails certificate checks on some Windows installs.
    kid = jwt.get_unverified_header(token)["kid"]
    if kid not in _keys.get(domain, {}):
        jwks = httpx.get(f"https://{domain}/.well-known/jwks.json", timeout=10).raise_for_status().json()
        _keys[domain] = {k["kid"]: jwt.PyJWK(k).key for k in jwks["keys"]}
    return _keys[domain][kid]


def public_config():
    domain = settings.get("AUTH0_DOMAIN")
    if not domain:
        return None
    return {"domain": domain, "clientId": settings.get("AUTH0_CLIENT_ID"),
            "audience": settings.get("AUTH0_AUDIENCE")}


def coordinator(authorization: str = Header(default="")):
    domain = settings.get("AUTH0_DOMAIN")
    if not domain:
        return "dev-mode"
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in as a coordinator")
    token = authorization[7:]
    try:
        key = _signing_key(domain, token)
        # leeway: a laptop clock a few seconds behind Auth0 otherwise rejects a token issued just now.
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings.get("AUTH0_AUDIENCE"), leeway=60,
                            issuer=f"https://{domain}/")
    except Exception as e:
        # Say why, so a misconfigured audience or tenant shows up on screen instead of a blank page.
        print(f"[auth] token rejected: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(401, f"Sign-in expired or invalid ({type(e).__name__}: {e})")
    return claims.get("sub", "unknown")
