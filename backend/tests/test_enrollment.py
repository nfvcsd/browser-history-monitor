import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, Mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine
from app.enrollment import verify_extension_identity
from app.main import app
from app.models import DeviceEnrollment, AuditEvent


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        if engine.url.database != "milestone_test":
            raise RuntimeError("Disposable test database required")
        Base.metadata.create_all(engine)
        self.client = TestClient(app)
        self.admin = {"X-Admin-Token": get_settings().dev_admin_token}
        self.settings = get_settings()
        self.patches = [
            patch.object(self.settings, "extension_auth_mode", "enrolled"),
            patch.object(
                self.settings,
                "extension_google_client_ids",
                "client.apps.googleusercontent.com",
            ),
            patch.object(self.settings, "extension_workspace_domains", "example.com"),
        ]
        for item in self.patches:
            item.start()
        self.claims = {
            "email": "alice@example.com",
            "sub": "google-alice",
            "hd": "example.com",
            "exp": int(time.time()) + 3600,
        }
        self.payload = {
            "device_key": "verified-device-one",
            "profile_subject": "google-alice",
            "extension_version": "0.4.0",
        }

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        Base.metadata.drop_all(engine)

    def enroll(self, **changes):
        with patch(
            "app.routes.enrollment.verify_extension_identity", return_value=self.claims
        ):
            return self.client.post(
                "/api/v1/enrollment",
                headers={"Authorization": "Bearer google-token"},
                json={**self.payload, **changes},
            )

    def test_credential_binding_renewal_revocation_and_legacy_denial(self):
        first = self.enroll()
        self.assertEqual(first.status_code, 200, first.text)
        data = first.json()
        headers = {"X-Device-Token": data["device_token"]}
        body = {
            "user_email": "alice@example.com",
            "device_key": self.payload["device_key"],
        }
        for route in ["batch", "policy"]:
            self.assertEqual(
                self.client.post(
                    "/api/v1/sync/" + route, headers=headers, json=body
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.post(
                    "/api/v1/sync/" + route,
                    headers=headers,
                    json={**body, "user_email": "bob@example.com"},
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.post(
                    "/api/v1/sync/" + route,
                    headers={"X-Extension-Token": self.settings.dev_extension_token},
                    json=body,
                ).status_code,
                401,
            )
        activity = {
            **body,
            "intervals": [
                {
                    "sample_id": "00000000-0000-4000-8000-000000000001",
                    "url": "https://example.com",
                    "started_at": (
                        datetime.now(timezone.utc) - timedelta(seconds=30)
                    ).isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/activity", headers=headers, json=activity
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/activity",
                headers=headers,
                json={**activity, "device_key": "different-device"},
            ).status_code,
            403,
        )
        with Session(engine) as db:
            row = db.scalar(select(DeviceEnrollment))
            self.assertNotEqual(row.credential_hash, data["device_token"])
            self.assertEqual(len(row.credential_hash), 64)
        renewed = self.enroll().json()
        self.assertNotEqual(renewed["device_token"], data["device_token"])
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/policy", headers=headers, json=body
            ).status_code,
            401,
        )
        headers = {"X-Device-Token": renewed["device_token"]}
        endpoint = f"/api/v1/enrollment/{data['device_id']}/revoke"
        self.assertEqual(self.client.post(endpoint, headers=headers).status_code, 401)
        self.assertEqual(
            self.client.post(endpoint, headers=self.admin).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/policy", headers=headers, json=body
            ).status_code,
            403,
        )
        self.assertEqual(self.enroll().status_code, 403)
        health = self.client.get("/api/v1/settings/devices", headers=self.admin).json()[
            "items"
        ][0]
        self.assertEqual(health["enrollment_status"], "revoked")
        with Session(engine) as db:
            events = db.scalars(select(AuditEvent)).all()
            self.assertTrue(any(event.action == "device.revoke" for event in events))
            self.assertTrue(
                all(data["device_token"] not in str(event.filters) for event in events)
            )

    def test_primary_profile_scope_expiry_and_domain_removal(self):
        self.assertEqual(self.enroll(profile_subject="other-account").status_code, 403)
        data = self.enroll().json()
        headers = {"X-Device-Token": data["device_token"]}
        body = {
            "user_email": "alice@example.com",
            "device_key": self.payload["device_key"],
        }
        with patch.object(
            self.settings, "extension_workspace_domains", "another.example"
        ):
            self.assertEqual(
                self.client.post(
                    "/api/v1/sync/policy", headers=headers, json=body
                ).status_code,
                403,
            )
        with Session(engine) as db:
            row = db.scalar(select(DeviceEnrollment))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/policy", headers=headers, json=body
            ).status_code,
            401,
        )
        self.claims = {**self.claims, "email": "bob@example.com", "sub": "google-bob"}
        self.assertEqual(self.enroll(profile_subject="google-bob").status_code, 409)

    def test_google_verification_audience_subject_domain_and_outages(self):
        info = {
            "aud": "client.apps.googleusercontent.com",
            "azp": "client.apps.googleusercontent.com",
            "sub": "google-alice",
            "exp": str(int(time.time()) + 3600),
            "scope": "openid https://www.googleapis.com/auth/userinfo.email",
        }
        profile = {
            "sub": "google-alice",
            "email": "alice@example.com",
            "email_verified": True,
            "hd": "example.com",
        }

        def response(body, status=200):
            return Mock(status_code=status, json=Mock(return_value=body))

        with patch(
            "app.enrollment.requests.get",
            side_effect=[response(info), response(profile)],
        ) as calls:
            self.assertEqual(
                verify_extension_identity("access-token")["email"], "alice@example.com"
            )
            self.assertEqual(
                calls.call_args_list[1].kwargs["headers"]["Authorization"],
                "Bearer access-token",
            )
        for changed in [
            {**info, "aud": "wrong"},
            {**info, "azp": "wrong"},
            {**info, "exp": "0"},
            {**info, "scope": "openid"},
        ]:
            with patch(
                "app.enrollment.requests.get", return_value=response(changed)
            ), self.assertRaises(HTTPException) as error:
                verify_extension_identity("access-token")
            self.assertEqual(error.exception.status_code, 401)
        for changed in [
            {**profile, "sub": "wrong"},
            {**profile, "email_verified": False},
            {**profile, "hd": "other.com"},
            {key: value for key, value in profile.items() if key != "hd"},
        ]:
            with patch(
                "app.enrollment.requests.get",
                side_effect=[response(info), response(changed)],
            ), self.assertRaises(HTTPException):
                verify_extension_identity("access-token")
        with patch(
            "app.enrollment.requests.get", return_value=response({}, 503)
        ), self.assertRaises(HTTPException) as error:
            verify_extension_identity("secret")
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret", error.exception.detail)
