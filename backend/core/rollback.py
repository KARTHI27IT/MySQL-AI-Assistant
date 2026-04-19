"""
core/rollback.py
Manages per-operation rollback snapshots and generates rollback SQL.
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from config import ROLLBACK_TTL_SECONDS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Rollback History Registry
# ─────────────────────────────────────────────────────────────

class RollbackHistory:
    """
    Stores pre-operation snapshots for INSERT / UPDATE / DELETE so they
    can be reversed within the TTL window.
    """

    def __init__(self, ttl_seconds: int = 300):
        self.history: Dict[str, Dict] = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    def add(
        self,
        database: str,
        sql: str,
        before_data: List[Dict],
        table_name: str,
        operation_type: str,
        primary_key: Optional[str] = None,
        auto_increment_col: Optional[str] = None,
        inserted_id: Optional[int] = None,
    ) -> str:
        """Register a new rollback snapshot and return its operation ID."""
        op_id = str(uuid.uuid4())
        self.history[op_id] = {
            "database":          database,
            "sql":               sql,
            "before_data":       before_data,
            "table_name":        table_name,
            "operation_type":    operation_type.upper(),
            "primary_key":       primary_key,
            "auto_increment_col": auto_increment_col,
            "inserted_id":       inserted_id,
            "created_at":        datetime.now(),
            "rolled_back":       False,
        }
        logger.info(
            f"[ROLLBACK] Registered {op_id} | {operation_type} on {table_name} "
            f"| rows: {len(before_data)}"
        )
        self._cleanup()
        return op_id

    def get(self, op_id: str) -> Optional[Dict]:
        """Return the snapshot if it exists, is not rolled back, and is not expired."""
        if op_id not in self.history:
            return None
        entry = self.history[op_id]
        if entry["rolled_back"]:
            return None
        if datetime.now() - entry["created_at"] > self.ttl:
            del self.history[op_id]
            return None
        return entry

    def expires_in(self, op_id: str) -> str:
        """Return a human-readable time remaining string."""
        if op_id not in self.history:
            return "expired"
        elapsed = (datetime.now() - self.history[op_id]["created_at"]).total_seconds()
        remaining = max(0, ROLLBACK_TTL_SECONDS - int(elapsed))
        m, s = divmod(remaining, 60)
        return f"{m}m {s}s" if m else f"{s}s"

    def mark_rolled_back(self, op_id: str):
        """Mark a snapshot as already rolled back so it cannot be used again."""
        if op_id in self.history:
            self.history[op_id]["rolled_back"] = True
            self.history[op_id]["rolled_back_at"] = datetime.now().isoformat()

    def _cleanup(self):
        """Remove expired and already-rolled-back entries."""
        expired = [
            k for k, v in self.history.items()
            if datetime.now() - v["created_at"] > self.ttl or v["rolled_back"]
        ]
        for k in expired:
            del self.history[k]


# Singleton instance used across the application
rollback_history = RollbackHistory(ttl_seconds=ROLLBACK_TTL_SECONDS)


# ─────────────────────────────────────────────────────────────
# Rollback SQL Builder
# ─────────────────────────────────────────────────────────────

def build_rollback_sql(operation: Dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Generate the SQL needed to undo a captured operation.
    Returns (rollback_sql, error_message). One of the two will be None.
    """
    table   = operation["table_name"]
    op_type = operation["operation_type"]
    before  = operation["before_data"]
    pk      = operation.get("primary_key")
    ins_id  = operation.get("inserted_id")

    if op_type == "DELETE":
        if not before:
            return None, "No captured rows to restore"
        cols     = list(before[0].keys())
        rows_sql = [
            f"({', '.join(_escape_val(row.get(c)) for c in cols)})"
            for row in before
        ]
        cols_str = ", ".join(f"`{c}`" for c in cols)
        return f"INSERT INTO `{table}` ({cols_str}) VALUES {', '.join(rows_sql)}", None

    if op_type == "UPDATE":
        if not before:
            return None, "No original data captured"
        if not pk:
            return None, f"No primary key on `{table}` — cannot safely rollback UPDATE"
        stmts = []
        for row in before:
            pk_val = row.get(pk)
            if pk_val is None:
                continue
            set_parts = [
                f"`{c}` = {_escape_val(v)}"
                for c, v in row.items() if c != pk
            ]
            if set_parts:
                stmts.append(
                    f"UPDATE `{table}` SET {', '.join(set_parts)} "
                    f"WHERE `{pk}` = {_escape_val(pk_val)}"
                )
        if not stmts:
            return None, "No rollback statements could be generated"
        return "; ".join(stmts), None

    if op_type == "INSERT":
        if ins_id and pk:
            return f"DELETE FROM `{table}` WHERE `{pk}` = {_escape_val(ins_id)}", None
        if before and pk:
            deletes = [
                f"DELETE FROM `{table}` WHERE `{pk}` = {_escape_val(r.get(pk))}"
                for r in before if r.get(pk) is not None
            ]
            if deletes:
                return "; ".join(deletes), None
        return None, f"No PK or inserted_id — cannot rollback INSERT on `{table}`"

    return None, f"Unsupported operation type: {op_type}"


# ─────────────────────────────────────────────────────────────
# Internal: Value Escaper
# ─────────────────────────────────────────────────────────────

def _escape_val(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'"
    if isinstance(val, (bytes, bytearray)):
        return f"X'{val.hex()}'"
    escaped = str(val).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"