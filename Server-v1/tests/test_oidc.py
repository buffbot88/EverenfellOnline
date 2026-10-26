import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import oidc  # noqa: E402
from db import Store  # noqa: E402


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def signed_token(private, claims, kid='test-key', alg='RS256'):
    header = b64url(json.dumps({'alg': alg, 'kid': kid}).encode())
    payload = b64url(json.dumps(claims).encode())
    message = f'{header}.{payload}'.encode()
    signature = private.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return f'{header}.{payload}.{b64url(signature)}'


class OidcVerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = cls.private.public_key().public_numbers()
        cls.key = {'kty': 'RSA', 'kid': 'test-key', 'use': 'sig', 'alg': 'RS256',
                   'n': b64url(public.n.to_bytes((public.n.bit_length() + 7) // 8, 'big')),
                   'e': b64url(public.e.to_bytes((public.e.bit_length() + 7) // 8, 'big'))}

    def setUp(self):
        self.old_discovery, self.old_jwks = oidc.discovery, oidc.jwks
        oidc.discovery = lambda force=False: {'issuer': oidc.ISSUER}
        oidc.jwks = lambda force=False: [self.key]

    def tearDown(self):
        oidc.discovery, oidc.jwks = self.old_discovery, self.old_jwks

    def claims(self, **updates):
        claims = {'iss': oidc.ISSUER, 'sub': 'agp-1', 'aud': oidc.CLIENT_ID,
                  'exp': 2_000_000_000, 'iat': 1_900_000_000,
                  'nonce': 'nonce-1', 'username': 'admin', 'role': ' Admin ',
                  'everenfell_s1': True}
        claims.update(updates)
        return claims

    def test_valid_signed_id_token_and_entitlement(self):
        identity = oidc.verify_id_token(signed_token(self.private, self.claims()), 'nonce-1', now=1_950_000_000)
        self.assertEqual(identity['sub'], 'agp-1')
        self.assertEqual(identity['role'], 'Admin')
        self.assertTrue(identity['everenfell_s1'])
        self.assertTrue(oidc.can_play(identity))

    def test_rejects_bad_nonce_audience_expiry_and_signature(self):
        token = signed_token(self.private, self.claims())
        with self.assertRaises(oidc.OidcError):
            oidc.verify_id_token(token, 'wrong', now=1_950_000_000)
        with self.assertRaises(oidc.OidcError):
            oidc.verify_id_token(signed_token(self.private, self.claims(aud='other')),
                                 'nonce-1', now=1_950_000_000)
        with self.assertRaises(oidc.OidcError):
            oidc.verify_id_token(signed_token(self.private, self.claims(exp=1)),
                                 'nonce-1', now=1_950_000_000)
        parts = token.split('.')
        parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
        with self.assertRaises(oidc.OidcError):
            oidc.verify_id_token('.'.join(parts), 'nonce-1', now=1_950_000_000)

    def test_non_admin_or_non_entitled_identity_cannot_play(self):
        for claims in (self.claims(role='Member'), self.claims(everenfell_s1=False)):
            identity = oidc.verify_id_token(signed_token(self.private, claims),
                                            'nonce-1', now=1_950_000_000)
            self.assertFalse(oidc.can_play(identity))


class OidcFlowAndTicketStoreTest(unittest.TestCase):
    def test_login_state_and_pkce_verifier_are_server_side(self):
        old_discovery = oidc.discovery
        oidc.discovery = lambda: {'authorization_endpoint': 'https://www.agpstudios.org/api/oauth/authorize'}
        class TxStore:
            transaction = None
            def create_oidc_transaction(self, *args):
                self.transaction = args
        store = TxStore()
        try:
            state, url = oidc.begin_login(store, now=100)
        finally:
            oidc.discovery = old_discovery
        query = parse_qs(urlparse(url).query)
        _, verifier, nonce, expiry = store.transaction
        expected = b64url(hashlib.sha256(verifier.encode()).digest())
        self.assertEqual(query['state'][0], state)
        self.assertEqual(query['nonce'][0], nonce)
        self.assertEqual(query['code_challenge'][0], expected)
        self.assertEqual(query['code_challenge_method'][0], 'S256')
        self.assertEqual(expiry, 100 + oidc.TRANSACTION_TTL)

    def test_transaction_and_gateway_ticket_are_one_use_and_bind_legacy_rows(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Store(os.path.join(raw, 'game.db'))
            self.addCleanup(store.close)
            store.create_oidc_transaction('state', 'verifier', 'nonce', 200)
            self.assertEqual(store.consume_oidc_transaction('state', now=199)['nonce'], 'nonce')
            self.assertIsNone(store.consume_oidc_transaction('state', now=199))
            store.create_oidc_transaction('expired', 'v', 'n', 100)
            self.assertIsNone(store.consume_oidc_transaction('expired', now=100))

            legacy = store.ensure_server_binding('agp-1', 'fu1304', 'old-account')
            self.assertEqual(legacy, 'old-account')
            self.assertIsNone(store.ensure_server_binding(
                'agp-1', 'fu1304', 'new-account', verified=True))
            self.assertEqual(store.get_server_binding('agp-1', 'fu1304')['game_account'],
                             'old-account')
            self.assertEqual(store.ensure_server_binding(
                'agp-2', 'fu1304', 'new-account', verified=True), 'new-account')
            self.assertTrue(store.get_server_binding('agp-2', 'fu1304')['verified'])

            identity = {'sub': 'agp-2', 'role': 'Admin', 'everenfell_s1': True}
            store.create_gateway_ticket('secret', 'jti-1', identity, 'S1',
                                        'fu1304', 'everenfell-gateway', 200, now=100)
            ticket = store.consume_gateway_ticket('secret', now=199)
            self.assertEqual(ticket['sub'], 'agp-2')
            self.assertIsNone(store.consume_gateway_ticket('secret', now=199))
            store.create_gateway_ticket('expired-secret', 'jti-2', identity, 'S1',
                                        'fu1304', 'everenfell-gateway', 100, now=90)
            self.assertIsNone(store.consume_gateway_ticket('expired-secret', now=100))


if __name__ == '__main__':
    unittest.main()
