"""AGP Studios OIDC authorization-code + PKCE client for Everenfell."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ISSUER = 'https://www.agpstudios.org/api/oauth'
CLIENT_ID = 'everenfell'
REDIRECT_URI = 'https://everenfell.agpstudios.org/auth/callback'
DISCOVERY_URL = ISSUER + '/.well-known/openid-configuration'
TRANSACTION_TTL = 600
CACHE_TTL = 600
_clock = time.time
_cache_lock = threading.Lock()
_discovery_cache = None
_jwks_cache = None


class OidcError(ValueError):
    pass


def _json_request(url, data=None):
    headers = {'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(data).encode()
    with urlopen(Request(url, data=data, headers=headers), timeout=8) as response:
        return json.loads(response.read(1_000_000))


def _trusted_endpoint(value):
    parsed = urlparse(value)
    return parsed.scheme == 'https' and parsed.hostname == urlparse(ISSUER).hostname


def discovery(force=False):
    global _discovery_cache
    now = _clock()
    with _cache_lock:
        if not force and _discovery_cache and _discovery_cache[0] > now:
            return _discovery_cache[1]
    doc = _json_request(DISCOVERY_URL)
    if not isinstance(doc, dict) or doc.get('issuer') != ISSUER:
        raise OidcError('untrusted OIDC issuer')
    for name in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
        if not isinstance(doc.get(name), str) or not _trusted_endpoint(doc[name]):
            raise OidcError('untrusted OIDC endpoint')
    if 'S256' not in doc.get('code_challenge_methods_supported', []):
        raise OidcError('OIDC provider lacks S256 PKCE')
    with _cache_lock:
        _discovery_cache = (now + CACHE_TTL, doc)
    return doc


def jwks(force=False):
    global _jwks_cache
    now = _clock()
    with _cache_lock:
        if not force and _jwks_cache and _jwks_cache[0] > now:
            return _jwks_cache[1]
    body = _json_request(discovery()['jwks_uri'])
    keys = body.get('keys') if isinstance(body, dict) else None
    if not isinstance(keys, list) or not keys:
        raise OidcError('OIDC provider has no signing keys')
    with _cache_lock:
        _jwks_cache = (now + CACHE_TTL, keys)
    return keys


def clear_cache():
    global _discovery_cache, _jwks_cache
    with _cache_lock:
        _discovery_cache = _jwks_cache = None


def begin_login(store, now=None):
    now = int(_clock()) if now is None else int(now)
    endpoint = discovery()['authorization_endpoint']
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    store.create_oidc_transaction(state, verifier, nonce, now + TRANSACTION_TTL)
    query = urlencode({
        'response_type': 'code', 'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI, 'scope': 'openid profile',
        'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'nonce': nonce,
    })
    return state, endpoint + ('&' if '?' in endpoint else '?') + query


def exchange_code(code, verifier):
    if not isinstance(code, str) or not code or not isinstance(verifier, str):
        raise OidcError('invalid authorization response')
    response = _json_request(discovery()['token_endpoint'], {
        'grant_type': 'authorization_code', 'code': code,
        'redirect_uri': REDIRECT_URI, 'client_id': CLIENT_ID,
        'code_verifier': verifier,
    })
    token = response.get('id_token') if isinstance(response, dict) else None
    if not isinstance(token, str) or not token:
        raise OidcError('OIDC token response missing id_token')
    return token


def _decode_part(part):
    return base64.b64decode(part + '=' * (-len(part) % 4), altchars=b'-_', validate=True)


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def _claims(token):
    try:
        if not isinstance(token, str):
            raise ValueError('not a string')
        header, payload, signature = token.split('.')
        return (json.loads(_decode_part(header)), json.loads(_decode_part(payload)),
                _decode_part(signature), f'{header}.{payload}'.encode())
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise OidcError('malformed ID token') from exc


def verify_id_token(token, nonce, now=None):
    now = _clock() if now is None else now
    header, claims, signature, signing_input = _claims(token)
    if (not isinstance(header, dict) or not isinstance(claims, dict)
            or header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str)):
        raise OidcError('unsupported ID token signature')
    verified = False
    for force in (False, True):
        key = next((item for item in jwks(force=force)
                    if isinstance(item, dict) and item.get('kid') == header['kid']
                    and item.get('kty') == 'RSA' and item.get('use', 'sig') == 'sig'
                    and item.get('alg', 'RS256') == 'RS256'), None)
        if key is None:
            continue
        try:
            n = int.from_bytes(_decode_part(key['n']), 'big')
            e = int.from_bytes(_decode_part(key['e']), 'big')
            if n.bit_length() < 2048 or e < 3 or e % 2 == 0:
                raise OidcError('weak OIDC signing key')
            rsa.RSAPublicNumbers(e, n).public_key().verify(
                signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
            verified = True
            break
        except InvalidSignature:
            continue
        except (KeyError, ValueError, TypeError) as exc:
            raise OidcError('invalid ID token key') from exc
    if not verified:
        raise OidcError('invalid ID token signature')

    audience = claims.get('aud')
    audiences = audience if isinstance(audience, list) else [audience]
    if (claims.get('iss') != ISSUER or CLIENT_ID not in audiences
            or (len(audiences) > 1 and claims.get('azp') != CLIENT_ID)
            or (claims.get('azp') is not None and claims.get('azp') != CLIENT_ID)):
        raise OidcError('invalid ID token issuer or audience')
    exp, issued = claims.get('exp'), claims.get('iat')
    if (isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp <= now
            or isinstance(issued, bool) or not isinstance(issued, (int, float))
            or issued > now + 30):
        raise OidcError('expired or invalid ID token time')
    not_before = claims.get('nbf')
    if not_before is not None and (isinstance(not_before, bool)
                                   or not isinstance(not_before, (int, float))
                                   or not_before > now + 30):
        raise OidcError('ID token is not yet valid')
    token_nonce = claims.get('nonce')
    if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce):
        raise OidcError('invalid ID token nonce')
    sub, username = claims.get('sub'), claims.get('username')
    if not isinstance(sub, str) or not sub or not isinstance(username, str) or not username:
        raise OidcError('ID token lacks a usable identity')
    role = claims.get('role')
    return {
        'sub': sub, 'username': username,
        'display_name': claims.get('display_name') if isinstance(claims.get('display_name'), str) else username,
        'email': claims.get('email') if isinstance(claims.get('email'), str) else '',
        'role': role.strip() if isinstance(role, str) else '',
        'everenfell_s1': claims.get('everenfell_s1') is True,
        'expires': int(exp),
    }


def can_play(identity):
    return (bool(identity)
            and str(identity.get('role', '')).strip().casefold() == 'admin'
            and identity.get('everenfell_s1') == 1)
