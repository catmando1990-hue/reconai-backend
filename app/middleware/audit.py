# app/middleware/audit.py
"""
Audit logging middleware for compliance (SOX, GDPR, CCPA).
Logs all data access and modifications for financial records.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import sqlite3
import json
from datetime import datetime
import uuid


class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    Audit logging middleware that tracks:
    - All API requests (method, path, user)
    - Data access (who viewed what)
    - Data modifications (create, update, delete)
    - Authentication events
    """

    def __init__(self, app, db_path: str = "data/reconai.db"):
        super().__init__(app)
        self.db_path = db_path
        self._init_audit_table()

    def _init_audit_table(self):
        """Create audit_logs table if it doesn't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                organization_id TEXT,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status_code INTEGER,
                ip_address TEXT,
                user_agent TEXT,
                request_body TEXT,
                response_body TEXT,
                metadata TEXT
            )
        """)

        # Create indexes for fast queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_user_id
            ON audit_logs(user_id, timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_org_id
            ON audit_logs(organization_id, timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_resource
            ON audit_logs(resource_type, resource_id, timestamp DESC)
        """)

        conn.commit()
        conn.close()

    def _should_log(self, path: str, method: str) -> bool:
        """Determine if this request should be audited"""
        # Skip health checks and static files
        if path in ["/", "/health", "/docs", "/openapi.json"]:
            return False

        # Log all API calls
        if path.startswith("/api/"):
            return True

        return False

    def _extract_user_id(self, request: Request) -> str:
        """Extract user ID from JWT token"""
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # In production, decode JWT to get user_id
            # For now, return a placeholder
            return "authenticated_user"
        return None

    def _extract_org_id(self, request: Request) -> str:
        """Extract organization ID from query params or body"""
        # Check query params
        org_id = request.query_params.get("org_id")
        if org_id:
            return org_id

        # For POST/PUT, would need to parse body
        # This is simplified - in production, cache body and parse
        return None

    def _classify_action(self, method: str, path: str) -> str:
        """Classify the action being performed"""
        if "auth" in path:
            return "AUTHENTICATION"
        elif method == "GET":
            return "READ"
        elif method == "POST":
            return "CREATE"
        elif method in ["PUT", "PATCH"]:
            return "UPDATE"
        elif method == "DELETE":
            return "DELETE"
        return "UNKNOWN"

    def _extract_resource_info(self, path: str):
        """Extract resource type and ID from path"""
        parts = path.split("/")

        # Example: /api/invoices/123 -> (invoices, 123)
        if len(parts) >= 4 and parts[1] == "api":
            resource_type = parts[2]
            resource_id = parts[3] if len(parts) > 3 else None
            return resource_type, resource_id

        return None, None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Skip if not auditable
        if not self._should_log(path, method):
            return await call_next(request)

        # Capture request info
        user_id = self._extract_user_id(request)
        org_id = self._extract_org_id(request)
        action = self._classify_action(method, path)
        resource_type, resource_id = self._extract_resource_info(path)
        ip_address = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        # Execute request
        start_time = datetime.now()
        response = await call_next(request)
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000

        # Log to database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO audit_logs (
                    id, timestamp, user_id, organization_id, action,
                    resource_type, resource_id, method, path, status_code,
                    ip_address, user_agent, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                datetime.now().isoformat(),
                user_id,
                org_id,
                action,
                resource_type,
                resource_id,
                method,
                path,
                response.status_code,
                ip_address,
                user_agent,
                json.dumps({"duration_ms": duration_ms})
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            # Don't fail the request if logging fails
            print(f"Audit log error: {e}")

        return response


def get_audit_logs(
    db_path: str,
    user_id: str = None,
    org_id: str = None,
    resource_type: str = None,
    resource_id: str = None,
    action: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 100
):
    """
    Query audit logs with filters.
    Used by audit log viewer endpoints.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    if org_id:
        query += " AND organization_id = ?"
        params.append(org_id)

    if resource_type:
        query += " AND resource_type = ?"
        params.append(resource_type)

    if resource_id:
        query += " AND resource_id = ?"
        params.append(resource_id)

    if action:
        query += " AND action = ?"
        params.append(action)

    if start_date:
        query += " AND timestamp >= ?"
        params.append(start_date)

    if end_date:
        query += " AND timestamp <= ?"
        params.append(end_date)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    columns = ["id", "timestamp", "user_id", "organization_id", "action",
               "resource_type", "resource_id", "method", "path", "status_code",
               "ip_address", "user_agent", "request_body", "response_body", "metadata"]

    return [dict(zip(columns, row)) for row in rows]
