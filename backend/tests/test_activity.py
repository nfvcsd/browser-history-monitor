import unittest
import uuid
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db import Base, engine
from app.main import app
from app.models import ActivityInterval


class ActivityTests(unittest.TestCase):
    def setUp(self):
        if engine.url.database != "milestone_test":
            raise RuntimeError("Disposable test database required")
        Base.metadata.create_all(engine)
        self.client = TestClient(app)
        self.admin = {"X-Admin-Token": get_settings().dev_admin_token}
        self.extension = {"X-Extension-Token": get_settings().dev_extension_token}
        self.base = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.client.close()
        Base.metadata.drop_all(engine)

    def payload(self, seconds=30, start=0, url="https://example.com/page", **changes):
        data = {"user_email": "alice@example.com", "device_key": "activity-device-1", "intervals": [{"sample_id": str(uuid.uuid4()), "url": url, "title": "Page title", "started_at": (self.base + timedelta(seconds=start)).isoformat(), "ended_at": (self.base + timedelta(seconds=start+seconds)).isoformat()}]}
        data.update(changes)
        return data

    def send(self, payload):
        return self.client.post("/api/v1/sync/activity", json=payload, headers=self.extension)

    def summary(self, **params):
        r = self.client.get("/api/v1/activity/summary", params=params, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_global_user_domain_page_and_clip(self):
        self.assertEqual(self.send(self.payload()).status_code, 200)
        self.assertEqual(self.send(self.payload(start=30, url="https://example.com/other")).status_code, 200)
        self.assertEqual(self.send(self.payload(user_email="bob@example.com", device_key="activity-device-2")).status_code, 200)
        total = self.summary()
        self.assertEqual(total["active_seconds"], 90)
        self.assertEqual(total["users"], 2)
        self.assertEqual(len(total["items"]), 2)
        self.assertEqual(total["items"][0]["active_seconds"], 60)
        domains = self.summary(group_by="domain")
        self.assertEqual(domains["items"][0]["active_seconds"], 90)
        people = self.summary(group_by="user")
        alice = next(row for row in people["items"] if row["key"] == "alice@example.com")
        own = self.summary(user_id=alice["user_id"])
        self.assertEqual(own["active_seconds"], 60)
        clipped = self.summary(start=(self.base+timedelta(seconds=15)).isoformat(), end=(self.base+timedelta(seconds=45)).isoformat())
        self.assertEqual(clipped["active_seconds"], 45)
        self.assertEqual(self.summary(domain="not-there")["samples"], 0)
        self.assertEqual(self.summary(q="Page title")["active_seconds"], 90)
        self.assertEqual(self.summary(q="%")["samples"], 0)
        first = self.summary(limit=1)
        second = self.summary(limit=1, offset=1)
        self.assertTrue(first["has_more"])
        self.assertNotEqual(first["items"][0]["key"], second["items"][0]["key"])

    def test_retry_overlap_and_ownership(self):
        payload = self.payload()
        self.assertEqual(self.send(payload).json(), {"accepted": 1, "duplicates": 0})
        self.assertEqual(self.send(payload).json(), {"accepted": 0, "duplicates": 1})
        self.assertEqual(self.summary()["active_seconds"], 30)
        self.assertEqual(self.send(self.payload(start=10)).status_code, 422)
        self.assertEqual(self.send(self.payload(start=30, user_email="someone@example.com")).status_code, 409)
        with Session(engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ActivityInterval)), 1)
        self.assertEqual(self.send(self.payload(start=30)).status_code, 200)

    def test_bounds_auth_and_old_history(self):
        self.assertEqual(self.summary()["samples"], 0)
        for payload in [self.payload(seconds=-1), self.payload(seconds=91), self.payload(url="chrome://settings"), self.payload(start=999999999)]:
            self.assertEqual(self.send(payload).status_code, 422)
        naive = self.payload(); naive["intervals"][0]["started_at"] = "2026-09-15T12:00:00"
        self.assertEqual(self.send(naive).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/sync/activity", json=self.payload(), headers=self.admin).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/activity/summary", headers=self.extension).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/activity/summary?group_by=bad", headers=self.admin).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/activity/summary?start=2026-09-16T00:00:00Z&end=2026-09-15T00:00:00Z", headers=self.admin).status_code, 422)
