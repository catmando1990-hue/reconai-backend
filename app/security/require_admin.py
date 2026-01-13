# BUILD 15 — Admin role enforcement helper (single truth source)

from __future__ import annotations

from fastapi import HTTPException

ADMIN_ROLES = {"admin", "org:admin"}


def require_admin(ctx) -> None:
    """
    Enforce admin role requirement.
    Raises 403 FORBIDDEN if user is not admin or org:admin.
    Use this instead of inline role checks for consistency.
    """
    role = getattr(ctx, "role", None)
    roles = set(getattr(ctx, "roles", []) or [])
    public_role = None
    try:
        public_role = ctx.claims.get("publicMetadata", {}).get("role")
    except Exception:
        public_role = None

    effective = set()
    if role:
        effective.add(str(role))
    if public_role:
        effective.add(str(public_role))
    effective |= {str(r) for r in roles}

    if not (effective & ADMIN_ROLES):
        raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "Admin required"})
