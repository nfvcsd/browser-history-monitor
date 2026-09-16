"""Integration checks against a disposable PostgreSQL database (never production)."""
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.main import app
from app.models import Device, HistoryVisit, User


class AdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.url.database != "milestone_test":
            raise RuntimeError("Tests require a disposable database named milestone_test")
        Base.metadata.create_all(engine)
        cls.client = TestClient(app)
        from app.config import get_settings
        cls.headers = {"X-Admin-Token": get_settings().dev_admin_token}
        cls.now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
        with Session(engine) as db:
            a = User(email="alice@example.test", display_name="Alice")
            b = User(email="bob@example.test")
            empty = User(email="empty@example.test")
            db.add_all([a, b, empty]); db.flush()
            cls.a, cls.empty = a.id, empty.id
            d1 = Device(user_id=a.id, device_key="device-1", last_sync_at=cls.now)
            d2 = Device(user_id=a.id, device_key="device-2", last_sync_at=cls.now + timedelta(hours=1))
            d3 = Device(user_id=b.id, device_key="device-3")
            db.add_all([d1, d2, d3]); db.flush()
            for i, (user, device, domain) in enumerate([(a, d1, "example.com"), (a, d2, "example.com"), (b, d3, "example.com"), (b, d3, "sub.example.com"), (b, d3, "")]):
                db.add(HistoryVisit(user_id=user.id, device_id=device.id, chrome_visit_id=str(i), url=f"https://{domain}/", domain=domain, visit_time=cls.now + timedelta(minutes=i), visit_count=99))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(engine)
        cls.client.close()

    def get(self, path, **params):
        response = self.client.get("/api/v1" + path, params=params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_users(self):
        rows = self.get("/users/summary")
        self.assertEqual(len(rows), 3)
        alice = rows[0]
        self.assertEqual((alice["device_count"], alice["visit_count"]), (2, 2))
        self.assertEqual(datetime.fromisoformat(alice["last_sync_at"]), self.now + timedelta(hours=1))
        empty = self.get(f"/users/{self.empty}")
        self.assertEqual((empty["device_count"], empty["visit_count"], empty["last_sync_at"]), (0, 0, None))
        self.assertEqual(len(self.get("/users/summary", q="ALICE")), 1)
        self.assertEqual(self.get("/users/summary", q="%"), [])
        self.assertEqual(self.get("/users/summary", limit=1, offset=1)[0]["email"], "bob@example.test")

    def test_domains_and_matching_history(self):
        rows = self.get("/domains")
        self.assertEqual(len(rows), 2)
        domain = rows[0]
        self.assertEqual((domain["domain"], domain["visit_count"], domain["unique_users"]), ("example.com", 3, 2))
        self.assertEqual(datetime.fromisoformat(domain["first_activity"]), self.now)
        self.assertEqual(datetime.fromisoformat(domain["last_activity"]), self.now + timedelta(minutes=2))
        self.assertEqual(len(self.get("/history", exact_domain="example.com")), 3)
        self.assertEqual(len(self.get("/history", domain="example.com")), 4)
        filters = {"user_id": str(self.a), "start": (self.now + timedelta(minutes=1)).isoformat(), "end": (self.now + timedelta(minutes=2)).isoformat()}
        filtered = self.get("/domains", **filters)
        self.assertEqual((filtered[0]["visit_count"], filtered[0]["unique_users"]), (1, 1))
        self.assertEqual(len(self.get("/history", exact_domain="example.com", **filters)), 1)
        self.assertEqual(self.get("/domains", q="%"), [])
        self.assertEqual(self.get("/domains", q="SUB")[0]["domain"], "sub.example.com")
        self.assertEqual(self.get("/domains", limit=1, offset=1)[0]["domain"], "sub.example.com")

    def test_overview_local_today(self):
        instant = datetime(2026, 9, 16, 2, tzinfo=timezone.utc)
        with patch("app.routes.admin.datetime", wraps=datetime) as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            self.assertEqual(self.get("/overview", timezone="UTC")["visits_today"], 0)
            self.assertEqual(self.get("/overview", timezone="America/Chicago")["visits_today"], 5)
        self.assertEqual(self.client.get("/api/v1/overview", params={"timezone": "Invalid/Zone"}, headers=self.headers).status_code, 422)

    def test_validation_auth_and_overview(self):
        for path in ["/users/summary", "/domains", f"/users/{self.a}", "/history", "/overview"]:
            self.assertEqual(self.client.get("/api/v1" + path).status_code, 401)
        for path in ["/domains?limit=0", "/domains?offset=-1", "/users/summary?limit=1001", "/users/not-a-uuid", "/domains?start=2026-09-16T00:00:00Z&end=2026-09-15T00:00:00Z"]:
            self.assertEqual(self.client.get("/api/v1" + path, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get(f"/api/v1/users/{uuid.uuid4()}", headers=self.headers).status_code, 404)
        stats = self.get("/overview")
        self.assertEqual((stats["users"], stats["devices"], stats["visits"], stats["domains"]), (3, 3, 5, 2))
        self.assertEqual(len(self.get("/users")), 3)
        self.assertEqual(len(self.get("/history", q="alice")), 2)
        first = self.get("/history", limit=2)
        second = self.get("/history", limit=2, offset=2)
        self.assertTrue(set(r["id"] for r in first).isdisjoint(r["id"] for r in second))


if __name__ == "__main__":
    unittest.main()
