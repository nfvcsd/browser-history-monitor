import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine
from app.main import app
from app.models import AuditEvent, Device, HistoryVisit, User


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.url.database != "milestone_test":
            raise RuntimeError(
                "Tests require a disposable database named milestone_test"
            )
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(email="monitored@example.test")
            db.add(user)
            db.flush()
            device = Device(user_id=user.id, device_key="audit-device")
            db.add(device)
            db.flush()
            cls.user_id = str(user.id)
            db.add(
                HistoryVisit(
                    user_id=user.id,
                    device_id=device.id,
                    chrome_visit_id="audit-visit",
                    url="https://example.test/",
                    domain="example.test",
                    title="Sensitive returned title",
                    visit_time=datetime(2026, 9, 15, 12, tzinfo=timezone.utc),
                )
            )
            db.commit()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(engine)

    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Admin-Token": get_settings().dev_admin_token}
        with Session(engine) as db:
            db.execute(delete(AuditEvent))
            db.commit()

    def events(self):
        with Session(engine) as db:
            return list(db.scalars(select(AuditEvent).order_by(AuditEvent.id)))

    def test_google_actor_and_filter_allowlist(self):
        settings = get_settings().model_copy(
            update={
                "auth_mode": "google",
                "google_client_id": "test-client",
                "google_workspace_domains": "school.test",
                "admin_emails": "admin@school.test",
            }
        )
        claims = {
            "sub": "verified-google-sub",
            "email": "admin@school.test",
            "email_verified": True,
            "hd": "school.test",
            "name": "Admin",
            "exp": 9999999999,
        }
        with patch("app.auth.get_settings", return_value=settings), patch(
            "app.auth.verify_google_token", return_value=claims
        ):
            response = self.client.get(
                "/api/v1/history",
                params={
                    "q": "example",
                    "user_id": self.user_id,
                    "actor_email": "forged@school.test",
                    "actor": "also-forged@school.test",
                    "token": "secret-query",
                },
                headers={
                    "Authorization": "Bearer private-credential",
                    "X-Admin-Token": "other-secret",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        (event,) = self.events()
        self.assertEqual(
            (event.actor_sub, event.actor_email, event.actor_mode),
            ("verified-google-sub", "admin@school.test", "google"),
        )
        self.assertEqual(event.action, "history.search")
        self.assertEqual(event.filters, {"q": "example", "user_id": self.user_id})
        self.assertEqual(event.result_count, 1)
        self.assertEqual(event.status_code, 200)
        self.assertIsNotNone(event.created_at.tzinfo)
        self.assertNotIn("private-credential", str(event.__dict__))
        self.assertNotIn("Sensitive returned title", str(event.__dict__))

    def test_report_and_export_requested(self):
        filters = {
            "start": "2026-09-15",
            "end": "2026-09-15",
            "timezone": "America/Chicago",
            "domain": "example.test",
        }
        report = self.client.get(
            "/api/v1/reports", params=filters, headers=self.headers
        )
        self.assertEqual(report.status_code, 200, report.text)
        export = self.client.get(
            "/api/v1/reports/export.csv", params=filters, headers=self.headers
        )
        self.assertEqual(export.status_code, 200)
        events = self.events()
        self.assertEqual(
            [e.action for e in events], ["reports.generate", "export.requested"]
        )
        self.assertEqual(events[0].result_count, 1)
        self.assertIsNone(events[1].result_count)
        self.assertEqual(events[0].filters, events[1].filters)
        self.assertEqual(events[0].actor_mode, "development")

    def test_failed_read_logged_but_unverified_actor_not_invented(self):
        response = self.client.get("/api/v1/history?limit=0", headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.events()[0].status_code, 422)
        self.assertEqual(self.client.get("/api/v1/history").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/audit").status_code, 401)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(
            self.client.get(
                "/api/v1/users/00000000-0000-0000-0000-000000000001",
                headers=self.headers,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.events()[-1].filters["user_id"], "00000000-0000-0000-0000-000000000001"
        )

    def test_read_and_export_fail_closed_if_audit_insert_fails(self):
        with patch(
            "app.audit.SessionLocal",
            side_effect=OperationalError("insert", {}, Exception("down")),
        ):
            for path in [
                "/history",
                "/reports?start=2026-09-15&end=2026-09-15",
                "/reports/export.csv?start=2026-09-15&end=2026-09-15",
            ]:
                response = self.client.get("/api/v1" + path, headers=self.headers)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("Sensitive returned title", response.text)
        self.assertEqual(self.events(), [])

    def test_read_connection_released_before_audit_transaction(self):
        from app.audit import SessionLocal as audit_session

        def checked_session():
            self.assertEqual(engine.pool.checkedout(), 0)
            return audit_session()

        with patch("app.audit.SessionLocal", side_effect=checked_session):
            response = self.client.get("/api/v1/history", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.events()), 1)

    def test_audit_filters_and_stable_cursor(self):
        for path in ["/history", "/history?q=example", "/domains"]:
            self.assertEqual(
                self.client.get("/api/v1" + path, headers=self.headers).status_code, 200
            )
        original_ids = [e.id for e in self.events()]
        first = self.client.get("/api/v1/audit?limit=2", headers=self.headers).json()
        self.assertEqual(
            [r["id"] for r in first["items"]], list(reversed(original_ids[1:]))
        )
        second = self.client.get(
            "/api/v1/audit",
            params={"limit": 2, "before_id": first["next_cursor"]},
            headers=self.headers,
        ).json()
        self.assertEqual([r["id"] for r in second["items"]], original_ids[:1])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(self.events()[-1].action, "audit.view")
        filtered = self.client.get(
            "/api/v1/audit",
            params={
                "action": "history.search",
                "actor": "development-admin",
                "start": "2020-01-01T00:00:00Z",
                "end": "2100-01-01T00:00:00Z",
            },
            headers=self.headers,
        ).json()
        self.assertEqual(len(filtered["items"]), 1)
        self.assertEqual(
            self.client.get("/api/v1/audit?actor=%25", headers=self.headers).json()[
                "items"
            ],
            [],
        )
        for query in [
            "action=unknown",
            "before_id=0",
            "limit=201",
            "start=2026-09-16T00:00:00Z&end=2026-09-15T00:00:00Z",
        ]:
            self.assertEqual(
                self.client.get(
                    "/api/v1/audit?" + query, headers=self.headers
                ).status_code,
                422,
            )
        for method in ["post", "put", "delete"]:
            self.assertEqual(
                getattr(self.client, method)(
                    "/api/v1/audit", headers=self.headers
                ).status_code,
                405,
            )
