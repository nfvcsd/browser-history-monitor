import csv
import io
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine
from app.main import app
from app.models import Device, HistoryVisit, User


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if engine.url.database != "milestone_test":
            raise RuntimeError(
                "Tests require a disposable database named milestone_test"
            )
        Base.metadata.create_all(engine)
        cls.client = TestClient(app)
        cls.headers = {"X-Admin-Token": get_settings().dev_admin_token}
        cls.filters = {"start": "2026-09-15", "end": "2026-09-16"}
        with Session(engine) as db:
            a, b = User(email="report-a@example.test"), User(
                email="report-b@example.test"
            )
            db.add_all([a, b])
            db.flush()
            d1, d2 = Device(
                user_id=a.id, device_key="report-device-a", device_name="=unsafe"
            ), Device(user_id=b.id, device_key="report-device-b")
            db.add_all([d1, d2])
            db.flush()
            cls.a, cls.d1 = a.id, d1.id
            events = [
                (a, d1, "example.com", "2026-09-14T23:59:59Z"),
                (a, d1, "example.com", "2026-09-15T00:00:00Z"),
                (b, d2, "example.com", "2026-09-15T23:59:59Z"),
                (a, d1, "sub.example.com", "2026-09-16T00:00:00Z"),
                (b, d2, "", "2026-09-16T23:59:59Z"),
                (a, d1, "example.com", "2026-09-17T00:00:00Z"),
            ]
            for i, (user, device, domain, timestamp) in enumerate(events):
                db.add(
                    HistoryVisit(
                        user_id=user.id,
                        device_id=device.id,
                        chrome_visit_id=f"report-{i}",
                        url=f"https://{domain}/",
                        domain=domain,
                        title='  =SUM(1,2)\n"Résumé"',
                        visit_time=datetime.fromisoformat(timestamp),
                        visit_count=99,
                    )
                )
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        Base.metadata.drop_all(engine)

    def request(self, endpoint="", **filters):
        response = self.client.get(
            "/api/v1/reports" + endpoint,
            params={**self.filters, **filters},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_aggregates_utc_boundaries_and_zero_buckets(self):
        report = self.request().json()
        self.assertEqual(
            (report["visits"], report["users"], report["devices"], report["domains"]),
            (4, 2, 2, 2),
        )
        self.assertEqual(report["timezone"], "UTC")
        self.assertEqual(
            report["daily"],
            [{"date": "2026-09-15", "visits": 2}, {"date": "2026-09-16", "visits": 2}],
        )
        self.assertEqual(len(report["hourly"]), 24)
        self.assertEqual(report["hourly"][0]["visits"], 2)
        self.assertEqual(report["hourly"][23]["visits"], 2)
        self.assertEqual(report["hourly"][1]["visits"], 0)
        self.assertEqual(
            report["top_domains"][0],
            {"domain": "example.com", "visit_count": 2, "unique_users": 2},
        )
        self.assertEqual(self.request(end="2026-09-15").json()["visits"], 2)

    def test_shared_filters_empty_and_csv_escaping(self):
        filters = {"user_id": str(self.a), "domain": "EXAMPLE.COM"}
        report = self.request(**filters).json()
        exported = self.request("/export.csv", **filters)
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(rows), report["visits"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["device_name"], "'=unsafe")
        self.assertEqual(rows[0]["title"], '\'  =SUM(1,2)\n"Résumé"')
        self.assertEqual(rows[0]["visit_time_utc"], "2026-09-15T00:00:00+00:00")
        self.assertIn("attachment", exported.headers["content-disposition"])
        self.assertEqual(exported.headers["cache-control"], "no-store")
        empty = self.request(domain="%").json()
        self.assertEqual(empty["visits"], 0)
        self.assertEqual(sum(day["visits"] for day in empty["daily"]), 0)
        self.assertEqual(empty["top_domains"], [])
        self.assertEqual(
            len(
                list(
                    csv.DictReader(
                        io.StringIO(self.request("/export.csv", domain="%").text)
                    )
                )
            ),
            0,
        )

    def test_export_streams_beyond_history_page_limit(self):
        with Session(engine) as db:
            db.add_all(
                [
                    HistoryVisit(
                        user_id=self.a,
                        device_id=self.d1,
                        chrome_visit_id=f"bulk-{i}",
                        url="https://bulk.test",
                        domain="bulk.test",
                        visit_time=datetime(2026, 9, 15, tzinfo=timezone.utc),
                    )
                    for i in range(1005)
                ]
            )
            db.commit()
        try:
            rows = list(
                csv.DictReader(
                    io.StringIO(self.request("/export.csv", domain="bulk.test").text)
                )
            )
            self.assertEqual(len(rows), 1005)
            self.assertEqual(len({row["visit_id"] for row in rows}), 1005)
        finally:
            with Session(engine) as db:
                db.execute(
                    delete(HistoryVisit).where(HistoryVisit.domain == "bulk.test")
                )
                db.commit()

    def test_validation_and_auth(self):
        for endpoint in ["", "/export.csv"]:
            path = "/api/v1/reports" + endpoint
            self.assertEqual(
                self.client.get(path, params=self.filters).status_code, 401
            )
            for filters in [
                {},
                {"start": "bad", "end": "2026-09-16"},
                {"start": "2026-09-17", "end": "2026-09-16"},
                {"start": "2020-01-01", "end": "2026-09-16"},
                {**self.filters, "user_id": "invalid"},
                {"start": "9999-12-31", "end": "9999-12-31"},
            ]:
                self.assertEqual(
                    self.client.get(
                        path, params=filters, headers=self.headers
                    ).status_code,
                    422,
                )
