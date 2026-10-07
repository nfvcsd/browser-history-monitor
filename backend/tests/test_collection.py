import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.collection import (
    Policy,
    DayWindow,
    scheduled,
    policy_record,
    make_permit,
    accepts,
    cleanup_retention,
    source_ip,
)
from app.config import get_settings
from app.db import Base, engine
from app.main import app
from app.models import (
    AuditEvent,
    ActivityInterval,
    Device,
    DeviceHealth,
    HistoryVisit,
    User,
)
from app.routes.activity import ActivityBatchIn


class CollectionTests(unittest.TestCase):
    def setUp(self):
        if engine.url.database != "milestone_test":
            raise RuntimeError("Disposable test database required")
        Base.metadata.create_all(engine)
        self.client = TestClient(app, client=("8.8.8.8", 1234))
        self.admin = {"X-Admin-Token": get_settings().dev_admin_token}
        self.ext = {"X-Extension-Token": get_settings().dev_extension_token}
        self.identity = {
            "user_email": "alice@example.com",
            "device_key": "policy-device-1",
            "extension_version": "0.3.0",
        }

    def tearDown(self):
        self.client.close()
        Base.metadata.drop_all(engine)

    def save(self, **changes):
        current = self.client.get("/api/v1/settings", headers=self.admin).json()
        result = self.client.post(
            "/api/v1/settings", headers=self.admin, json={**current, **changes}
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def check(self, **changes):
        result = self.client.post(
            "/api/v1/sync/policy", headers=self.ext, json={**self.identity, **changes}
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_settings_validation_conflict_and_transactional_audit(self):
        current = self.save(retention_days=30)
        for change in [
            {"timezone": "bad/zone"},
            {"public_ips": ["192.168.1.1"]},
            {"public_ips": ["8.8.8.0/24"]},
            {"retention_days": 0},
            {"days": []},
        ]:
            result = self.client.post(
                "/api/v1/settings", headers=self.admin, json={**current, **change}
            )
            self.assertEqual(result.status_code, 422)
        stale = {**current, "revision": current["revision"] - 1}
        self.assertEqual(
            self.client.post(
                "/api/v1/settings", headers=self.admin, json=stale
            ).status_code,
            409,
        )
        self.assertEqual(self.client.get("/api/v1/settings").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/v1/settings", headers=self.ext, json=current
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/sync/policy", headers=self.admin, json=self.identity
            ).status_code,
            401,
        )
        with Session(engine) as db:
            event = db.scalar(
                select(AuditEvent).where(AuditEvent.action == "settings.update")
            )
            self.assertEqual(event.filters["after"]["retention_days"], 30)
            self.assertNotIn("signing_key", event.filters["after"])
        # Failure to write the audit record must also roll back the settings edit.
        with patch(
            "sqlalchemy.orm.Session.commit",
            side_effect=RuntimeError("database unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/v1/settings",
                    headers=self.admin,
                    json={**current, "retention_days": 5},
                )
        self.assertEqual(
            self.client.get("/api/v1/settings", headers=self.admin).json()[
                "retention_days"
            ],
            30,
        )

    def test_schedule_overnight_dst_and_boundaries(self):
        policy = Policy(schedule_enabled=True)
        policy.days[0] = DayWindow(enabled=True, start="08:00", end="16:00")

        def at(value):
            return datetime.fromisoformat(value)

        self.assertFalse(scheduled(policy, at("2026-10-05T12:59:59+00:00")))
        self.assertTrue(scheduled(policy, at("2026-10-05T13:00:00+00:00")))
        self.assertFalse(scheduled(policy, at("2026-10-05T21:00:00+00:00")))
        self.assertTrue(scheduled(policy, at("2026-11-02T14:00:00+00:00")))
        policy.days[6] = DayWindow(enabled=True, start="22:00", end="02:00")
        self.assertTrue(scheduled(policy, at("2026-10-05T06:59:59+00:00")))
        self.assertFalse(scheduled(policy, at("2026-10-05T07:00:00+00:00")))
        policy.days[6] = DayWindow(enabled=True, start="01:00", end="02:00")
        self.assertTrue(scheduled(policy, at("2026-11-01T06:30:00+00:00")))
        self.assertTrue(scheduled(policy, at("2026-11-01T07:30:00+00:00")))
        self.assertFalse(scheduled(policy, at("2026-11-01T08:00:00+00:00")))

    def test_ip_modes_empty_list_and_forwarded_spoofing(self):
        self.save(ip_enabled=True, public_ips=["8.8.8.8"])
        self.assertTrue(self.check()["allowed"])
        self.save(public_ips=[])
        self.assertFalse(self.check()["allowed"])
        self.save(public_ips=["1.1.1.1"])
        response = self.client.post(
            "/api/v1/sync/policy",
            headers={**self.ext, "X-Forwarded-For": "1.1.1.1"},
            json={**self.identity, "public_ip": "1.1.1.1"},
        )
        self.assertFalse(response.json()["allowed"])
        self.save(ip_source="device")
        self.assertFalse(self.check()["allowed"])
        self.assertTrue(self.check(public_ip="1.1.1.1")["allowed"])
        self.assertFalse(self.check(public_ip="192.168.0.1")["allowed"])
        self.save(public_ips=["2606:4700:4700::1111"])
        self.assertTrue(self.check(public_ip="2606:4700:4700:0:0:0:0:1111")["allowed"])
        request = Request(
            {
                "type": "http",
                "client": ("10.0.0.2", 123),
                "headers": [(b"x-forwarded-for", b"1.1.1.1, 8.8.8.8, 10.0.0.3")],
            }
        )
        with patch.object(get_settings(), "trusted_proxy_cidrs", "10.0.0.0/24"):
            self.assertEqual(source_ip(request), "8.8.8.8")
        with patch.object(get_settings(), "trusted_proxy_cidrs", ""):
            self.assertEqual(source_ip(request), "10.0.0.2")

    def test_restricted_ingestion_requires_collection_evidence(self):
        self.save(ip_enabled=True, public_ips=["8.8.8.8"])
        policy = self.check()
        start = datetime.fromisoformat(policy["valid_from"])
        visits = [
            {
                "chrome_visit_id": "one",
                "url": "https://example.com",
                "visit_time": start.isoformat(),
            }
        ]
        result = self.client.post(
            "/api/v1/sync/batch",
            headers=self.ext,
            json={**self.identity, "visits": visits},
        )
        self.assertEqual(result.json()["filtered"], 1)
        visits[0]["collection_permit"] = policy["permit"]
        result = self.client.post(
            "/api/v1/sync/batch",
            headers=self.ext,
            json={**self.identity, "visits": visits},
        )
        self.assertEqual(result.json()["accepted"], 1)
        interval = {
            "sample_id": str(uuid.uuid4()),
            "url": "https://example.com",
            "started_at": start.isoformat(),
            "ended_at": (start + timedelta(seconds=20)).isoformat(),
            "collection_permit": policy["permit"],
        }

        def send(item):
            return self.client.post(
                "/api/v1/sync/activity",
                headers=self.ext,
                json={**self.identity, "intervals": [item]},
            ).json()

        self.assertEqual(send(interval)["accepted"], 1)
        self.assertEqual(send(interval)["duplicates"], 1)
        self.assertEqual(
            send(
                {
                    **interval,
                    "sample_id": str(uuid.uuid4()),
                    "collection_permit": policy["permit"] + "a",
                }
            )["filtered"],
            1,
        )
        self.assertEqual(
            send(
                {**interval, "started_at": (start - timedelta(minutes=1)).isoformat()}
            )["filtered"],
            1,
        )
        self.assertEqual(
            send({**interval, "ended_at": (start + timedelta(seconds=60)).isoformat()})[
                "filtered"
            ],
            1,
        )
        with Session(engine) as db:
            record = policy_record(db)
            payload = ActivityBatchIn(**{**self.identity, "intervals": [interval]})
            self.assertTrue(
                accepts(
                    record,
                    payload,
                    payload.intervals[0],
                    start,
                    start + timedelta(seconds=20),
                    now=start + timedelta(days=1),
                )
            )
            payload.device_key = "different-device"
            self.assertFalse(
                accepts(
                    record,
                    payload,
                    payload.intervals[0],
                    start,
                    start + timedelta(seconds=20),
                )
            )
        self.save(ip_enabled=True, public_ips=[])
        self.assertEqual(send(interval)["filtered"], 1)
        with Session(engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(ActivityInterval)), 1
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(HistoryVisit)), 1
            )

    def test_health_paused_stale_and_retention(self):
        self.save(schedule_enabled=True)
        self.assertEqual(self.check()["reason"], "outside_schedule")
        health = self.client.get("/api/v1/settings/devices", headers=self.admin).json()
        self.assertEqual(health["items"][0]["status"], "outside_schedule")
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            device = db.scalar(select(Device))
            heartbeat = db.get(DeviceHealth, device.id)
            heartbeat.checked_at = now - timedelta(hours=1)
            db.add(
                HistoryVisit(
                    user_id=device.user_id,
                    device_id=device.id,
                    url="https://example.com",
                    domain="example.com",
                    visit_time=now - timedelta(days=3),
                    chrome_visit_id="old",
                )
            )
            db.add(
                ActivityInterval(
                    user_id=device.user_id,
                    device_id=device.id,
                    url="https://example.com",
                    domain="example.com",
                    sample_id=uuid.uuid4(),
                    started_at=now - timedelta(days=3),
                    ended_at=now - timedelta(days=3) + timedelta(seconds=20),
                )
            )
            db.add(
                ActivityInterval(
                    user_id=device.user_id,
                    device_id=device.id,
                    url="https://example.com",
                    domain="example.com",
                    sample_id=uuid.uuid4(),
                    started_at=now - timedelta(days=1, seconds=10),
                    ended_at=now - timedelta(days=1) + timedelta(seconds=10),
                )
            )
            db.commit()
            self.assertEqual(cleanup_retention(db, now), 0)
        self.assertEqual(
            self.client.get("/api/v1/settings/devices", headers=self.admin).json()[
                "items"
            ][0]["status"],
            "not_reporting",
        )
        self.save(retention_days=1, schedule_enabled=False)
        with Session(engine) as db:
            self.assertEqual(cleanup_retention(db, now), 2)
            interval = db.scalar(select(ActivityInterval))
            self.assertEqual(interval.started_at, now - timedelta(days=1))
            self.assertGreater(
                db.scalar(select(func.count()).select_from(AuditEvent)), 0
            )
            self.assertEqual(db.scalar(select(func.count()).select_from(User)), 1)
        old = {
            "chrome_visit_id": "old",
            "url": "https://example.com",
            "visit_time": (now - timedelta(days=3)).isoformat(),
        }
        result = self.client.post(
            "/api/v1/sync/batch",
            headers=self.ext,
            json={**self.identity, "visits": [old]},
        )
        self.assertEqual(result.json()["filtered"], 1)

    def test_concurrent_edits_do_not_overwrite(self):
        from concurrent.futures import ThreadPoolExecutor
        current = self.client.get("/api/v1/settings", headers=self.admin).json()
        # Avoid starting lifespan workers in this concurrency test: only requests
        # need concurrency, not independent application startup/shutdown.
        def request_update(days):
            client = TestClient(app)
            try:
                return client.post("/api/v1/settings", headers=self.admin, json={**current, "retention_days": days}).status_code
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request_update, [10, 20]))
        self.assertEqual(sorted(results), [200, 409])
