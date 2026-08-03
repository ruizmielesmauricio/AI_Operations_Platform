"""Test-only stand-in for Supabase's real JWKS endpoint (app.security.auth).

Real tokens are ES256, signed with Supabase's project key and verified
against its published JWKS. Tests can't reach that over the network (and
shouldn't need to), so this generates a throwaway EC key pair once per test
process, signs test tokens with the private half, and monkeypatches
app.security.auth._jwks_client to hand back the public half instead of
fetching a real JWKS document.
"""

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

_private_key = ec.generate_private_key(ec.SECP256R1())
_public_key = _private_key.public_key()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(_public_key)


def patch_jwks(monkeypatch) -> None:
    from app.security import auth

    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJWKClient())


def bearer_header(user_id: str, email: str) -> dict:
    token = jwt.encode(
        {"sub": user_id, "email": email, "aud": "authenticated"},
        _private_key,
        algorithm="ES256",
    )
    return {"Authorization": f"Bearer {token}"}
