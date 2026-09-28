"""Audit authenticated reads before their response body is released."""

import json

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .db import SessionLocal
from .models import AuditEvent

ACTIONS = {
    "activity_summary": "activity.view",
    "overview": "overview.view",
    "list_users": "users.list",
    "user_summaries": "users.list",
    "user_detail": "user.view",
    "domains": "domains.view",
    "history": "history.view",
    "report": "reports.generate",
    "export_report": "export.requested",
    "audit_log": "audit.view",
}
FILTER_KEYS = {
    "activity_summary": {"group_by", "user_id", "domain", "q", "start", "end", "limit", "offset"},
    "overview": {"timezone"},
    "list_users": set(),
    "user_summaries": {"q", "limit", "offset"},
    "user_detail": set(),
    "domains": {"q", "user_id", "start", "end", "limit", "offset"},
    "history": {
        "user_id",
        "domain",
        "exact_domain",
        "q",
        "start",
        "end",
        "limit",
        "offset",
    },
    "report": {"start", "end", "timezone", "user_id", "domain"},
    "export_report": {"start", "end", "timezone", "user_id", "domain"},
    "audit_log": {"actor", "action", "start", "end", "before_id", "limit"},
}


def write_event(
    identity: dict, action: str, filters: dict, status: int, count: int | None, read_session=None
):
    try:
        # The JSON response is already serialized. Return the read connection
        # before opening the audit transaction so concurrent reads cannot exhaust
        # the pool while all waiting for a second connection. CSV opens its own
        # session later, after this audit succeeds.
        if read_session is not None:
            read_session.close()
        # Independent transaction: audit records survive a failed read transaction.
        with SessionLocal() as db:
            db.add(
                AuditEvent(
                    actor_sub=identity["sub"],
                    actor_email=identity["email"],
                    actor_mode=identity["mode"],
                    action=action,
                    status_code=status,
                    filters=filters,
                    result_count=count,
                )
            )
            db.commit()
    except SQLAlchemyError:
        # Never release unlogged history/report/export data.
        raise HTTPException(503, "Audit logging is unavailable. Please retry later.")


class AuditedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        action = ACTIONS[self.endpoint.__name__]
        filter_keys = FILTER_KEYS[self.endpoint.__name__]

        async def handle(request: Request):
            selected_action = action
            filters = {
                key: value[:4096]
                for key, value in request.query_params.items()
                if key in filter_keys
            }
            if any(
                len(value) > 4096
                for key, value in request.query_params.items()
                if key in filter_keys
            ):
                filters["values_truncated"] = True
            if "user_id" in request.path_params:
                filters["user_id"] = str(request.path_params["user_id"])
            if action == "history.view" and any(
                filters.get(key)
                for key in ("q", "domain", "exact_domain", "user_id", "start", "end")
            ):
                selected_action = "history.search"
            try:
                response = await original(request)
            except Exception as exc:
                identity = getattr(request.state, "admin_identity", None)
                if identity:
                    status = (
                        422
                        if isinstance(exc, RequestValidationError)
                        else getattr(exc, "status_code", 500)
                    )
                    await run_in_threadpool(
                        write_event, identity, selected_action, filters, status, None,
                        getattr(request.state, "database_session", None)
                    )
                raise
            identity = getattr(request.state, "admin_identity", None)
            if identity is None:
                raise HTTPException(500, "Missing audit identity")
            count = None
            body = getattr(response, "body", None)
            if body and response.media_type == "application/json":
                data = json.loads(body)
                if isinstance(data, list):
                    count = len(data)
                elif action == "reports.generate":
                    count = data.get("visits")
                elif action == "audit.view":
                    count = len(data.get("items", []))
            await run_in_threadpool(
                write_event,
                identity,
                selected_action,
                filters,
                response.status_code,
                count,
                getattr(request.state, "database_session", None),
            )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle
