"""
utils/audit.py
Append-only audit log writer.
"""
import logging
from datetime import datetime

from config import AUDIT_LOG_FILE

logger = logging.getLogger(__name__)


def audit_log(operation: str, user: str, database: str, sql: str, result: str):
    """
    Append a structured audit entry to the audit log file.

    Args:
        operation: High-level operation name (e.g. 'WRITE', 'ROLLBACK', 'ERROR').
        user:      Identifier for the acting user (anonymous if not authenticated).
        database:  Target database name.
        sql:       The SQL statement (truncated to 200 chars for safety).
        result:    Short result description (e.g. 'OK rows=3').
    """
    ts       = datetime.now().isoformat()
    safe_sql = (sql[:200].replace('\n', ' ') if sql else "N/A")
    entry    = f"[{ts}] {operation} | {user} | DB:{database} | SQL:{safe_sql} | {result}\n"
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(entry)
    except Exception as e:
        logger.error(f"Audit log failed: {e}")