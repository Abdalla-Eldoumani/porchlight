"""Coordinator login through Auth0. The dashboard gets an access token from
Auth0 and sends it as a Bearer token; we check its signature, audience and
issuer here. With no Auth0 domain set the server runs open (dev mode)."""
import jwt
from fastapi import Header, HTTPException

from . import settings

_jwks = {}   # domain -> PyJWKClient, so keys are fetched once per domain


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
        client = _jwks.setdefault(domain, jwt.PyJWKClient(f"https://{domain}/.well-known/jwks.json"))
        key = client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings.get("AUTH0_AUDIENCE"),
                            issuer=f"https://{domain}/")
    except Exception:
        raise HTTPException(401, "Sign-in expired or invalid")
    return claims.get("sub", "unknown")
