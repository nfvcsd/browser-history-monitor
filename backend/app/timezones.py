from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException


def report_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=422, detail="Unknown IANA timezone")
