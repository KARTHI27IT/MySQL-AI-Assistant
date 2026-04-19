"""
utils/sql_helpers.py
Pure SQL utility functions: extraction, classification, validation, preview,
schema formatting, and INSERT helpers.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

from config import MYSQL_CONFIG

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# SQL Parsing Helpers
# ─────────────────────────────────────────────────────────────

def extract_sql(raw: str) -> Optional[str]:
    """Strip markdown fences and extract the first valid SQL statement."""
    if not raw:
        return None
    out = raw.strip()
    out = re.sub(r'```sql\s*', '', out, flags=re.IGNORECASE)
    out = re.sub(r'```\s*', '', out).strip()

    pattern = (
        r'(?i)(?:^|\n)\s*'
        r'(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO'
        r'|SHOW|DESCRIBE|DESC|EXPLAIN)\s+.*?;'
    )
    m = re.search(pattern, out, re.DOTALL | re.IGNORECASE)
    if m:
        sql = m.group(0).strip()
        sql = re.sub(r'\s*;?\s*```.*$', ';', sql, flags=re.IGNORECASE)
        return sql if sql.endswith(';') else sql + ';'

    if re.search(r'(?i)^\s*(SELECT|INSERT|UPDATE|DELETE|SHOW|DESC)', out):
        sql = re.sub(
            r'(?i)^.*?(SELECT|INSERT|UPDATE|DELETE|SHOW|DESCRIBE|EXPLAIN)',
            r'\1', out, count=1, flags=re.IGNORECASE
        )
        sql = re.sub(
            r'\s*(```|Thought:|Answer:|Final\s*Answer:).*$', '',
            sql, flags=re.IGNORECASE | re.DOTALL
        ).strip()
        if sql and not sql.endswith(';'):
            sql += ';'
        if re.match(r'(?i)^(SELECT|INSERT|UPDATE|DELETE|SHOW|DESCRIBE|EXPLAIN)', sql):
            return sql

    return None


def valid_dml_prefix(sql: str) -> bool:
    """Return True if SQL starts with an allowed DML/query keyword."""
    if not sql:
        return False
    allowed = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE',
               'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN', 'WITH')
    return any(sql.strip().upper().startswith(p) for p in allowed)


def classify_query(sql: str) -> str:
    """
    Classify a SQL statement as READ, WRITE, BLOCKED_<CMD>, or UNKNOWN.
    DDL / DCL commands are returned as BLOCKED_*.
    """
    if not sql:
        return "UNKNOWN"
    clean = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL).strip().lower()

    if clean.startswith(('select', 'with', 'show', 'describe', 'desc', 'explain')):
        return "READ"
    if clean.startswith(('insert', 'update', 'delete', 'replace')):
        return "WRITE"

    for pattern, name in [
        (r'^create\s+',   'CREATE'),
        (r'^drop\s+',     'DROP'),
        (r'^alter\s+',    'ALTER'),
        (r'^truncate\s+', 'TRUNCATE'),
        (r'^rename\s+',   'RENAME'),
        (r'^grant\s+',    'GRANT'),
        (r'^revoke\s+',   'REVOKE'),
    ]:
        if re.search(pattern, clean, re.IGNORECASE):
            return f"BLOCKED_{name}"

    return "UNKNOWN"


def extract_table(sql: str) -> Optional[str]:
    """Best-effort extraction of the primary table name from a SQL statement."""
    if not sql:
        return None
    low = sql.lower().strip()
    for pat in [
        r'insert\s+into\s+`?(\w+)`?',
        r'update\s+`?(\w+)`?',
        r'delete\s+from\s+`?(\w+)`?',
        r'select\s+.*?\s+from\s+`?(\w+)`?',
    ]:
        m = re.search(pat, low)
        if m:
            return m.group(1)
    fb = re.search(r'(?:from|into|update)\s+`?(\w+)`?', low)
    return fb.group(1) if fb else None


def extract_where(sql: str) -> Optional[str]:
    """Extract the WHERE clause body from a SQL statement."""
    if not sql:
        return None
    m = re.search(
        r'where\s+(.+?)(?:;|$|order\s+by|group\s+by|limit)',
        sql, re.IGNORECASE | re.DOTALL
    )
    return m.group(1).strip() if m else None


# ─────────────────────────────────────────────────────────────
# Schema Formatting
# ─────────────────────────────────────────────────────────────

def format_schema(schema: Dict) -> str:
    """Convert a schema dict into a human-readable string for LLM prompts."""
    lines = [f"Database: {schema['database']}", ""]
    for tn, ti in schema["tables"].items():
        lines.append(f"TABLE: {tn}")
        if ti["comment"]:
            lines.append(f"  Description: {ti['comment']}")
        lines.append("  Columns:")
        for col in ti["columns"]:
            pk = "[PK] " if col['is_key'] else ""
            ai = "[AI] " if col.get('auto_increment') else ""
            nn = "NOT NULL" if not col['nullable'] else "NULL"
            lines.append(f"    {pk}{ai}{col['name']}: {col['type']} {nn}")
        if ti["primary_key"]:
            lines.append(f"  Primary Key: {ti['primary_key']}")
        if ti.get("auto_increment"):
            lines.append(f"  Auto Increment: {ti['auto_increment']}")
        if ti["foreign_keys"]:
            lines.append("  Relationships:")
            for fk in ti["foreign_keys"]:
                lines.append(
                    f"    {fk['column']} -> {fk['references_table']}.{fk['references_column']}"
                )
        lines.append("")
    if schema["relationships"]:
        lines.append("RELATIONSHIP SUMMARY:")
        for rel in schema["relationships"]:
            lines.append(f"  {rel['from']} <-> {rel['to']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Write Safety Validation
# ─────────────────────────────────────────────────────────────

def validate_write_sql(sql: str) -> Tuple[bool, str]:
    """
    Perform basic safety checks on a write statement.
    Rejects dangerous patterns that lack a WHERE clause.
    """
    low = sql.lower().strip()
    dangerous = [
        r'drop\s+\w+',
        r'truncate\s+\w+',
        r'alter\s+\w+',
        r'create\s+\w+',
        r'delete\s+from\s+\w+\s*;',
        r'update\s+\w+\s+set\s+.+?\s*;',
    ]
    for p in dangerous:
        if re.search(p, low) and 'where' not in low:
            return False, f"Dangerous pattern without WHERE: {p}"
    if low.startswith(('update', 'delete')) and 'where' not in low:
        return False, "UPDATE/DELETE requires a WHERE clause for safety"
    return True, "OK"


# ─────────────────────────────────────────────────────────────
# Write Preview
# ─────────────────────────────────────────────────────────────

def preview_write(sql: str, database: str) -> Dict[str, Any]:
    """
    Estimate the impact of a write statement without executing it.
    Returns a dict with affected_count, sample rows, warning, etc.
    """
    conn = None
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG, database=database)
        cursor = conn.cursor(dictionary=True)
        low = sql.lower().strip()

        for op, fpat in [
            ('delete', r'from\s+`?(\w+)`?'),
            ('update', r'update\s+`?(\w+)`?'),
        ]:
            if low.startswith(op):
                tm = re.search(fpat, sql, re.IGNORECASE)
                wm = re.search(
                    r'where\s+(.+?)(?:;|$|order\s+by|group\s+by|limit)',
                    sql, re.IGNORECASE
                )
                if tm:
                    tbl = tm.group(1)
                    wh  = f" WHERE {wm.group(1)}" if wm else ""
                    cursor.execute(f"SELECT COUNT(*) as cnt FROM `{tbl}`{wh}")
                    count = (cursor.fetchone() or {}).get('cnt', 0)
                    cursor.execute(f"SELECT * FROM `{tbl}`{wh} LIMIT 5")
                    sample = cursor.fetchall() or []
                    return {
                        "action":         op.upper(),
                        "affected_count": count,
                        "sample":         sample,
                        "warning":        f"⚠️ {count} row(s) will be {op.upper()}D",
                        "table":          tbl,
                    }

        if low.startswith('insert'):
            m = re.match(
                r"insert\s+into\s+`?(\w+)`?\s*\(([^)]+)\)\s*values\s*\(([^)]+)\)",
                sql, re.IGNORECASE
            )
            if m:
                tbl, cols, vals = m.groups()
                return {
                    "action":         "INSERT",
                    "affected_count": 1,
                    "sample":         [],
                    "warning":        "New row will be inserted",
                    "table":          tbl,
                    "columns":        [c.strip().strip('`') for c in cols.split(',')],
                    "values":         [v.strip().strip("'\"") for v in vals.split(',')],
                }

        return {"warning": "Could not estimate impact", "action": "UNKNOWN",
                "affected_count": 0, "sample": []}

    except Exception as e:
        logger.error(f"preview_write: {e}")
        return {"error": str(e), "warning": "Preview failed", "affected_count": 0, "sample": []}
    finally:
        if conn and conn.is_connected():
            conn.close()


# ─────────────────────────────────────────────────────────────
# Capture Before-State (for rollback)
# ─────────────────────────────────────────────────────────────

def capture_before_state(
    conn,
    sql: str,
    table: str,
    op_type: str,
    max_rollback_rows: int = 1000,
) -> Tuple[List[Dict], Optional[str], Optional[str]]:
    """
    Snapshot the rows that will be affected by an UPDATE or DELETE.
    Returns (rows, primary_key_col, auto_increment_col).
    """
    from core.database import get_primary_key
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        pk, ai = get_primary_key(conn, table)
        where  = extract_where(sql)
        wclause = f" WHERE {where}" if where else ""
        limit   = f" LIMIT {max_rollback_rows}" if op_type.upper() in ('UPDATE', 'DELETE') else ""
        cursor.execute(f"SELECT * FROM `{table}`{wclause}{limit}")
        rows = cursor.fetchall()
        if len(rows) >= max_rollback_rows:
            logger.warning(f"[CAPTURE] Capped at {max_rollback_rows} rows")
        return rows or [], pk, ai
    except Exception as e:
        logger.error(f"capture_before_state: {e}")
        return [], None, None
    finally:
        if cursor:
            cursor.close()


# ─────────────────────────────────────────────────────────────
# INSERT Helpers
# ─────────────────────────────────────────────────────────────

def coerce_value(value: Any, data_type: str) -> Any:
    """Cast a raw form value to the appropriate Python type for mysql-connector binding."""
    if value is None or value == "":
        return None

    dt = data_type.lower()

    if dt in ("int", "bigint", "smallint", "tinyint", "mediumint", "year"):
        try:
            return int(value)
        except (ValueError, TypeError):
            return value

    if dt in ("float", "double", "decimal", "numeric", "real"):
        try:
            return float(value)
        except (ValueError, TypeError):
            return value

    if isinstance(value, bool):
        return int(value)

    return str(value)


def build_insert_sql(
    table: str,
    data: Dict[str, Any],
    columns: List[Dict],
) -> Tuple[str, list]:
    """
    Build a parameterised INSERT SQL and the corresponding values list.
    Auto-increment columns are always skipped.
    Empty optional fields become NULL.
    """
    col_map      = {c["name"]: c for c in columns}
    insert_cols  = []
    placeholders = []
    values       = []

    for col_name, raw_val in data.items():
        col_meta = col_map.get(col_name)
        if col_meta is None or col_meta["auto_increment"]:
            continue
        coerced = coerce_value(raw_val, col_meta["data_type"])
        insert_cols.append(f"`{col_name}`")
        placeholders.append("%s")
        values.append(coerced)

    if not insert_cols:
        raise ValueError("No valid columns to insert")

    sql = (
        f"INSERT INTO `{table}` ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join(placeholders)})"
    )
    return sql, values