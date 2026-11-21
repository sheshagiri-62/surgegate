"""JWT checks for Cognito access tokens.

Every protected request carries `Authorization: Bearer <access token>`. The token is accepted
only if ALL of these hold:

* signature valid (RS256) with a key from the user pool's JWKS (public keys, cached);
* `iss` is our user pool, `exp` is in the future (60 s clock skew allowed);
* `token_use` is "access" (an ID token is rejected) and `client_id` is one of our app clients.

Roles come from `cognito:groups` (set only by an admin). Organisers must also carry a
`tenant_id` claim, added by the pre-token-generation Lambda from the admin-only attribute
custom:tenant_id. Tenant scoping in the endpoints always uses this claim, never a value from
the URL or the request body.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

BUYER = "buyer"
ORGANISER = "organiser"


@dataclass(frozen=True)
class AuthSettings:
    issuer: str
    client_ids: frozenset[str]
    jwks_url: str = ""
    leeway_seconds: int = 60

    @property
    def jwks(self) -> str:
        return self.jwks_url or f"{self.issuer}/.well-known/jwks.json"


@dataclass(frozen=True)
class Principal:
    """The signed-in caller, taken only from verified token claims."""

    sub: str
    groups: frozenset[str] = field(default_factory=frozenset)
    tenant_id: uuid.UUID | None = None

    @property
    def is_organiser(self) -> bool:
        return ORGANISER in self.groups

    @property
    def is_buyer(self) -> bool:
        return BUYER in self.groups


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
    region = os.getenv("AWS_REGION", "ap-south-1")
    issuer = os.getenv("COGNITO_ISSUER") or (
        f"https://cognito-idp.{region}.amazonaws.com/{pool_id}" if pool_id else ""
    )
    clients = frozenset(c for c in os.getenv("COGNITO_CLIENT_IDS", "").split(",") if c)
    return AuthSettings(
        issuer=issuer, client_ids=clients, jwks_url=os.getenv("COGNITO_JWKS_URL", "")
    )


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    # Keys are cached for an hour; an unknown "kid" triggers one refetch (key rotation).
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=5)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def verify_access_token(token: str, settings: AuthSettings) -> Principal:
    if not settings.issuer or not settings.client_ids:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication not configured")
    try:
        key = _jwks_client(settings.jwks).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=settings.issuer,
            leeway=settings.leeway_seconds,
            # Cognito access tokens have no "aud"; client_id is checked below instead.
            options={"require": ["exp", "iat", "iss", "sub", "token_use"], "verify_aud": False},
        )
    except jwt.PyJWKClientError as exc:
        raise _unauthorized("unknown signing key") from exc
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("invalid token") from exc

    if claims.get("token_use") != "access":
        raise _unauthorized("access token required")
    if claims.get("client_id") not in settings.client_ids:
        raise _unauthorized("unknown client")

    tenant_id = None
    if raw := claims.get("tenant_id"):
        try:
            tenant_id = uuid.UUID(raw)
        except ValueError as exc:
            raise _unauthorized("invalid tenant claim") from exc

    return Principal(
        sub=claims["sub"],
        groups=frozenset(claims.get("cognito:groups", [])),
        tenant_id=tenant_id,
    )


_bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("missing bearer token")
    return verify_access_token(credentials.credentials, settings)


def require_buyer(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not principal.is_buyer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "buyer role required")
    return principal


def require_organiser(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not principal.is_organiser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "organiser role required")
    if principal.tenant_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "organiser has no tenant")
    return principal


Buyer = Annotated[Principal, Depends(require_buyer)]
Organiser = Annotated[Principal, Depends(require_organiser)]
AnyUser = Annotated[Principal, Depends(current_principal)]
