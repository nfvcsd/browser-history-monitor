"""Real signed JWT verification with locally supplied Google public certificates."""

import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
from google.auth.exceptions import TransportError

from app.config import Settings
from app.main import app


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.signer = crypt.RSASigner.from_string(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            key_id="test-key",
        )
        cls.public_key = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    def setUp(self):
        self.settings = Settings(
            database_url="postgresql+psycopg://localhost/milestone_test",
            dev_extension_token="extension-secret",
            dev_admin_token="dev-secret",
            auth_mode="google",
            google_client_id="client.apps.googleusercontent.com",
            google_workspace_domains=" Example.org ",
            admin_emails=" Admin@Example.org ",
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        for target, value in [
            ("app.auth.get_settings", self.settings),
            ("app.routes.auth.get_settings", self.settings),
        ]:
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        certificates = patch(
            "google.oauth2.id_token._fetch_certs",
            return_value={"test-key": self.public_key},
        )
        certificates.start()
        self.addCleanup(certificates.stop)

    def token(self, **changes):
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": self.settings.google_client_id,
            "sub": "google-123",
            "iat": now - 5,
            "exp": now + 3600,
            "email": "admin@example.org",
            "email_verified": True,
            "hd": "example.org",
            "name": "Administrator",
        }
        claims.update(changes)
        return jwt.encode(self.signer, claims).decode()

    def me(self, token=None, **headers):
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        return self.client.get("/api/v1/auth/me", headers=headers)

    def test_valid_google_identity_and_public_config(self):
        response = self.me(self.token())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sub"], "google-123")
        self.assertEqual(response.json()["email"], "admin@example.org")
        self.assertEqual(response.headers["cache-control"], "no-store")
        config = self.client.get("/api/v1/auth/config").json()
        self.assertEqual(config["mode"], "google")
        self.assertTrue(config["configured"])
        self.assertNotIn("admin_emails", config)
        self.assertNotIn("dev-secret", str(config))

    def test_crypto_claim_validation(self):
        for claims in [
            {"aud": "another-client"},
            {"iss": "https://attacker.test"},
            {"exp": int(time.time()) - 60},
            {"iat": int(time.time()) + 3600},
            {"sub": ""},
        ]:
            with self.subTest(claims=claims):
                self.assertEqual(self.me(self.token(**claims)).status_code, 401)
        self.assertEqual(self.me("not-a-jwt").status_code, 401)
        token = self.token()
        header, payload, signature = token.split(".")
        self.assertEqual(
            self.me(
                f"{header}.{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
            ).status_code,
            401,
        )

    def test_domain_verified_email_and_allowlist(self):
        for claims in [
            {"email": "viewer@example.org"},
            {"hd": "other.org"},
            {"hd": None},
            {"email_verified": False},
            {"email_verified": "true"},
            {"email": "admin@example.org.attacker.test"},
        ]:
            with self.subTest(claims=claims):
                self.assertEqual(self.me(self.token(**claims)).status_code, 403)
        # Reuse a valid token after removing administrator access.
        token = self.token()
        self.assertEqual(self.me(token).status_code, 200)
        self.settings.admin_emails = "another@example.org"
        self.assertEqual(self.me(token).status_code, 403)

    def test_google_mode_rejects_development_token_on_all_admin_routes(self):
        for path in [
            "/auth/me",
            "/overview",
            "/users",
            "/users/summary",
            "/users/00000000-0000-0000-0000-000000000001",
            "/domains",
            "/history",
            "/reports?start=2026-01-01&end=2026-01-02",
            "/reports/export.csv?start=2026-01-01&end=2026-01-02",
        ]:
            response = self.client.get(
                "/api/v1" + path, headers={"X-Admin-Token": "dev-secret"}
            )
            self.assertEqual(response.status_code, 401, path)
        self.assertEqual(self.me().status_code, 401)

    def test_development_mode_and_extension_are_separate(self):
        self.settings.auth_mode = "development"
        self.assertEqual(self.me(**{"X-Admin-Token": "dev-secret"}).status_code, 200)
        self.assertEqual(self.me(self.token()).status_code, 401)
        self.assertEqual(
            self.me(**{"X-Extension-Token": "extension-secret"}).status_code, 401
        )
        self.assertEqual(self.me(**{"X-Admin-Token": "wrong"}).status_code, 401)
        response = self.client.post(
            "/api/v1/sync/batch",
            json={},
            headers={"X-Extension-Token": "extension-secret"},
        )
        self.assertEqual(
            response.status_code, 422
        )  # Extension passes auth but payload is invalid.
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/batch", json={}, headers={"X-Admin-Token": "dev-secret"}
            ).status_code,
            401,
        )

    def test_missing_configuration_and_network_fail_closed(self):
        with patch(
            "app.auth.verify_google_token", side_effect=TransportError("network down")
        ):
            self.assertEqual(self.me(self.token()).status_code, 503)
        self.settings.admin_emails = ""
        self.assertFalse(self.client.get("/api/v1/auth/config").json()["configured"])
        self.assertEqual(
            self.me(self.token(), **{"X-Admin-Token": "dev-secret"}).status_code, 503
        )

    def test_cors_supports_bearer_header(self):
        response = self.client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Authorization", response.headers["access-control-allow-headers"])
