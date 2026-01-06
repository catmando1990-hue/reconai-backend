from __future__ import annotations

from fastapi import HTTPException


def not_authenticated(message: str = "Authentication required") -> None:
    raise HTTPException(
        status_code=401,
        detail={
            "error": "NOT_AUTHENTICATED",
            "message": message,
        },
    )


def org_required(message: str = "Active organization required") -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "error": "ORG_REQUIRED",
            "message": message,
        },
    )


def not_authorized(message: str = "Not authorized") -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "error": "NOT_AUTHORIZED",
            "message": message,
        },
    )


def plan_limit(message: str = "Plan limit reached") -> None:
    raise HTTPException(
        status_code=402,
        detail={
            "error": "PLAN_LIMIT",
            "message": message,
        },
    )
