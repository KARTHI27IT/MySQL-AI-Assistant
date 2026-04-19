"""
core/database.py
Handles MySQL connections, schema fetching, and low-level query execution.
"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector
from mysql.connector import errorcode
from datetime import datetime

from config import MYSQL_CONFIG, MAX_EXECUTION_TIME_MS, MAX_RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Connection Helpers
# ─────────────────────────────────────────────────────────────

def get_base_connection():
    """Return a connection without a specific database (for SHOW DATABASES, health, etc.)."""
    return mysql.connector.connect(**MYSQL_CONFIG)


def get_db_connection(database: str):
    """Return a connection scoped to the given database."""
    return mysql.connector.connect(**MYSQL_CONFIG, database=database)


# ─────────────────────────────────────────────────────────────
# Schema Fetching
# ─────────────────────────────────────────────────────────────

def fetch_schema(db: str) -> Dict[str, Any]:
    """
    Introspect the given database and return a structured schema dict
    containing tables, columns, primary keys, foreign keys, and relationships.
    """
    conn = None
    try:
        conn = get_db_connection(db)
        cur  = conn.cursor(dictionary=True)
        schema: Dict[str, Any] = {
            "database": db,
            "tables": {},
            "relationships": [],
            "fetched_at": datetime.now().isoformat()
        }

        cur.execute(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'", (db,)
        )
        for tbl in cur.fetchall():
            tn = tbl['TABLE_NAME']
            schema["tables"][tn] = {
                "comment": tbl['TABLE_COMMENT'] or "",
                "columns": [],
                "primary_key": None,
                "foreign_keys": [],
                "auto_increment": None,
            }

            cur.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                       COLUMN_KEY, EXTRA, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                ORDER BY ORDINAL_POSITION
            """, (db, tn))
            for col in cur.fetchall():
                schema["tables"][tn]["columns"].append({
                    "name":           col['COLUMN_NAME'],
                    "type":           col['DATA_TYPE'],
                    "nullable":       col['IS_NULLABLE'] == 'YES',
                    "default":        col['COLUMN_DEFAULT'],
                    "is_key":         col['COLUMN_KEY'] in ['PRI', 'MUL'],
                    "auto_increment": 'auto_increment' in (col['EXTRA'] or ''),
                    "comment":        col['COLUMN_COMMENT'] or "",
                })
                if col['COLUMN_KEY'] == 'PRI':
                    schema["tables"][tn]["primary_key"] = col['COLUMN_NAME']
                if 'auto_increment' in (col['EXTRA'] or ''):
                    schema["tables"][tn]["auto_increment"] = col['COLUMN_NAME']

            cur.execute("""
                SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL
            """, (db, tn))
            for fk in cur.fetchall():
                schema["tables"][tn]["foreign_keys"].append({
                    "column":             fk['COLUMN_NAME'],
                    "references_table":   fk['REFERENCED_TABLE_NAME'],
                    "references_column":  fk['REFERENCED_COLUMN_NAME'],
                })
                schema["relationships"].append({
                    "from": f"{tn}.{fk['COLUMN_NAME']}",
                    "to":   f"{fk['REFERENCED_TABLE_NAME']}.{fk['REFERENCED_COLUMN_NAME']}",
                })

        cur.close()
        return schema

    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_BAD_DB_ERROR:
            raise ValueError(f"Database '{db}' does not exist")
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()


# ─────────────────────────────────────────────────────────────
# Query Execution
# ─────────────────────────────────────────────────────────────

def execute_query(conn, sql: str, query_type: str) -> Tuple[bool, Any, Optional[str]]:
    """
    Execute a SQL statement with retry logic.
    Returns (success, result_dict, error_message).
    """
    cursor = None
    last_err = "Unknown error after retries"

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(f"SET SESSION max_execution_time = {MAX_EXECUTION_TIME_MS}")

            if query_type == "READ":
                cursor.execute(sql)
                if cursor.description:
                    cols = [d[0] for d in cursor.description]
                    rows = [_serialize_row(r) for r in cursor.fetchall()]
                    return True, {"columns": cols, "rows": rows, "row_count": len(rows)}, None
                return True, {"message": "Executed (no results)", "rows": []}, None

            elif query_type == "WRITE":
                cursor.execute(sql)
                return True, {
                    "rows_affected": cursor.rowcount,
                    "last_insert_id": cursor.lastrowid if sql.lower().strip().startswith('insert') else None,
                }, None

        except mysql.connector.Error as err:
            last_err = f"MySQL {err.errno}: {err.msg}"
            if conn:
                conn.rollback()
            if err.errno not in [1205, 1213, 2006, 2013] or attempt >= MAX_RETRY_ATTEMPTS:
                return False, None, last_err
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        except Exception as e:
            last_err = str(e)
            if conn:
                conn.rollback()
            if attempt >= MAX_RETRY_ATTEMPTS:
                return False, None, last_err
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        finally:
            if cursor:
                cursor.close()

    return False, None, last_err


# ─────────────────────────────────────────────────────────────
# Primary Key Detection
# ─────────────────────────────────────────────────────────────

def get_primary_key(conn, table: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (primary_key_column, auto_increment_column) for the given table."""
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME='PRIMARY'
        """, (table,))
        r = cursor.fetchone()
        pk = r['COLUMN_NAME'] if r else None

        cursor.execute("""
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND EXTRA LIKE '%auto_increment%'
        """, (table,))
        r = cursor.fetchone()
        ai = r['COLUMN_NAME'] if r else None
        return pk, ai

    except Exception as e:
        logger.warning(f"PK detect failed: {e}")
        return None, None
    finally:
        if cursor:
            cursor.close()


# ─────────────────────────────────────────────────────────────
# Table Data Fetch
# ─────────────────────────────────────────────────────────────

def fetch_table_data(conn, table: str, where: Optional[str] = None, limit: int = 100) -> Dict:
    """Fetch rows from a table with optional WHERE clause, returning serialised result."""
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        wclause = f" WHERE {where}" if where else ""
        try:
            cursor.execute(f"SELECT * FROM `{table}`{wclause} ORDER BY 1 DESC LIMIT {limit}")
        except Exception:
            cursor.execute(f"SELECT * FROM `{table}`{wclause} LIMIT {limit}")

        rows = cursor.fetchall()
        if not cursor.description:
            return {"table": table, "columns": [], "rows": [], "row_count": 0}

        cols = [d[0] for d in cursor.description]
        serialized = [_serialize_row(r) for r in rows]
        return {
            "table": table,
            "columns": cols,
            "rows": serialized,
            "row_count": len(serialized),
            "limit_applied": limit,
        }
    except Exception as e:
        logger.error(f"fetch_table_data: {e}")
        return {"error": str(e), "table": table, "rows": []}
    finally:
        if cursor:
            cursor.close()


# ─────────────────────────────────────────────────────────────
# Insert Column Metadata
# ─────────────────────────────────────────────────────────────

def fetch_insert_columns(database: str, table: str) -> List[Dict]:
    """
    Return rich column metadata for building an insert form.
    Includes: name, data_type, display_type, nullable, has_default,
              default_value, auto_increment, enum_values, char_max_length, comment.
    """
    import re
    conn = None
    try:
        conn = get_db_connection(database)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE,
                COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT,
                CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (database, table))
        rows = cursor.fetchall()
        cursor.close()

        columns = []
        for row in rows:
            is_ai     = 'auto_increment' in (row['EXTRA'] or '').lower()
            nullable  = row['IS_NULLABLE'] == 'YES'
            has_default = row['COLUMN_DEFAULT'] is not None or nullable

            enum_values: List[str] = []
            col_type_str = row['COLUMN_TYPE'] or ""
            if row['DATA_TYPE'] == 'enum':
                enum_values = re.findall(r"'([^']*)'", col_type_str)

            columns.append({
                "name":              row['COLUMN_NAME'],
                "data_type":         row['DATA_TYPE'],
                "display_type":      col_type_str,
                "nullable":          nullable,
                "has_default":       has_default,
                "default_value":     row['COLUMN_DEFAULT'],
                "auto_increment":    is_ai,
                "enum_values":       enum_values,
                "char_max_length":   row['CHARACTER_MAXIMUM_LENGTH'],
                "numeric_precision": row['NUMERIC_PRECISION'],
                "numeric_scale":     row['NUMERIC_SCALE'],
                "comment":           row['COLUMN_COMMENT'] or "",
            })
        return columns

    except Exception as e:
        logger.error(f"fetch_insert_columns: {e}")
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()


# ─────────────────────────────────────────────────────────────
# Internal: Row Serialiser
# ─────────────────────────────────────────────────────────────

def _serialize_row(row: dict) -> list:
    result = []
    for v in row.values():
        if hasattr(v, 'isoformat'):
            result.append(v.isoformat())
        elif isinstance(v, (bytes, bytearray)):
            result.append(v.decode('utf-8', errors='replace'))
        else:
            result.append(v)
    return result