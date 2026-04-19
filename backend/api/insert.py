"""
api/insert.py
Routes:
  GET  /insert/tables/{database}          — List tables with stats (for table selector)
  GET  /insert/schema/{database}/{table}  — Rich column metadata (for dynamic form)
  POST /insert                            — Execute a parameterised INSERT
"""
import logging

import mysql.connector
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import ALLOW_WRITE_OPERATIONS, WRITE_TABLE_PREVIEW_LIMIT, MAX_EXECUTION_TIME_MS
from core.database import (
    get_db_connection, fetch_insert_columns, fetch_table_data, get_primary_key
)
from core.rollback import rollback_history
from utils.sql_helpers import build_insert_sql
from utils.audit import audit_log
from utils.serializers import InsertRequest

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# GET /insert/tables/{database}
# ─────────────────────────────────────────────────────────────

@router.get("/insert/tables/{database}")
def get_insert_tables(database: str):
    """
    Return a list of user tables in the database with approximate row counts
    and column counts, used to populate the Insert Modal table selector.
    """
    conn = None
    try:
        conn = get_db_connection(database)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                t.TABLE_NAME       AS name,
                t.TABLE_ROWS       AS row_count,
                COUNT(c.COLUMN_NAME) AS column_count
            FROM information_schema.TABLES t
            LEFT JOIN information_schema.COLUMNS c
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME
            WHERE t.TABLE_SCHEMA = %s AND t.TABLE_TYPE = 'BASE TABLE'
            GROUP BY t.TABLE_NAME, t.TABLE_ROWS
            ORDER BY t.TABLE_NAME
        """, (database,))
        tables = cursor.fetchall()
        cursor.close()

        return {
            "database": database,
            "tables": [
                {
                    "name":         t["name"],
                    "row_count":    int(t["row_count"]) if t["row_count"] is not None else 0,
                    "column_count": int(t["column_count"]),
                }
                for t in tables
            ],
        }

    except mysql.connector.Error as err:
        logger.error(f"get_insert_tables: {err}")
        return JSONResponse(
            status_code=400,
            content={"error": f"MySQL {err.errno}: {err.msg}", "tables": []}
        )
    except Exception as e:
        logger.error(f"get_insert_tables: {e}")
        return JSONResponse(status_code=500, content={"error": str(e), "tables": []})
    finally:
        if conn and conn.is_connected():
            conn.close()


# ─────────────────────────────────────────────────────────────
# GET /insert/schema/{database}/{table}
# ─────────────────────────────────────────────────────────────

@router.get("/insert/schema/{database}/{table}")
def get_insert_schema(database: str, table: str):
    """
    Return rich column metadata for a specific table so the frontend
    can render a dynamic insert form with correct input types,
    required-field markers, and enum dropdowns.
    """
    try:
        columns = fetch_insert_columns(database, table)
        return {
            "database": database,
            "table":    table,
            "columns":  columns,
            "total_columns": len(columns),
            "required_columns": sum(
                1 for c in columns
                if not c["nullable"] and not c["has_default"] and not c["auto_increment"]
            ),
        }
    except mysql.connector.Error as err:
        logger.error(f"get_insert_schema: {err}")
        return JSONResponse(
            status_code=400,
            content={"error": f"MySQL {err.errno}: {err.msg}", "columns": []}
        )
    except Exception as e:
        logger.error(f"get_insert_schema: {e}")
        return JSONResponse(status_code=500, content={"error": str(e), "columns": []})


# ─────────────────────────────────────────────────────────────
# POST /insert
# ─────────────────────────────────────────────────────────────

@router.post("/insert")
def insert_row(req: InsertRequest):
    """
    Execute a parameterised INSERT built from Insert Modal form data.
    Validates required fields, coerces types, and registers a rollback snapshot.
    """
    if not ALLOW_WRITE_OPERATIONS:
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": "Write operations are disabled on this server."}
        )

    database = req.database
    table    = req.table
    data     = req.data

    logger.info(f"[INSERT] Manual insert into `{database}`.`{table}` | cols: {list(data.keys())}")

    conn = None
    try:
        # 1. Fetch column metadata
        columns = fetch_insert_columns(database, table)
        if not columns:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Table `{table}` not found or has no columns."}
            )

        # 2. Validate required fields
        col_map = {c["name"]: c for c in columns}
        missing = [
            col_name
            for col_name, col_meta in col_map.items()
            if not col_meta["auto_increment"]
            and not col_meta["nullable"]
            and not col_meta["has_default"]
            and (data.get(col_name) is None or data.get(col_name) == "")
        ]
        if missing:
            return JSONResponse(
                status_code=422,
                content={
                    "success": False,
                    "error": f"Missing required field(s): {', '.join(missing)}",
                    "missing_fields": missing,
                }
            )

        # 3. Build parameterised SQL
        sql, values = build_insert_sql(table, data, columns)
        logger.info(f"[INSERT] SQL: {sql} | values: {values}")

        # 4. Execute
        conn = get_db_connection(database)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SET SESSION max_execution_time = {MAX_EXECUTION_TIME_MS}")
        cursor.execute(sql, values)
        inserted_id   = cursor.lastrowid
        rows_affected = cursor.rowcount
        cursor.close()
        conn.commit()

        logger.info(f"[INSERT] Success — inserted_id={inserted_id}, rows_affected={rows_affected}")
        audit_log("INSERT", "anonymous", database, sql, f"OK inserted_id={inserted_id}")

        # 5. Table preview
        table_data = fetch_table_data(conn, table, limit=WRITE_TABLE_PREVIEW_LIMIT)

        # 6. Register rollback snapshot
        operation_id = None
        pk_col, ai_col = get_primary_key(conn, table)
        if pk_col and inserted_id:
            cur2 = conn.cursor(dictionary=True)
            cur2.execute(f"SELECT * FROM `{table}` WHERE `{pk_col}` = %s", (inserted_id,))
            inserted_row = cur2.fetchone()
            cur2.close()
            if inserted_row:
                operation_id = rollback_history.add(
                    database, sql, [inserted_row], table, "INSERT",
                    primary_key=pk_col,
                    auto_increment_col=ai_col,
                    inserted_id=inserted_id,
                )

        rollback_exp = rollback_history.expires_in(operation_id) if operation_id else None

        return {
            "success":           True,
            "sql":               sql,
            "query_type":        "WRITE",
            "rows_affected":     rows_affected,
            "last_insert_id":    inserted_id,
            "table_name":        table,
            "table_data":        table_data or {},
            "operation_id":      operation_id,
            "rollback_available": operation_id is not None,
            "rollback_expires_in": rollback_exp,
            "message":           f"Row inserted into `{table}` — ID {inserted_id}",
        }

    except ValueError as e:
        logger.error(f"[INSERT] ValueError: {e}")
        if conn: conn.rollback()
        return JSONResponse(status_code=422, content={"success": False, "error": str(e)})

    except mysql.connector.Error as err:
        logger.error(f"[INSERT] MySQL error: {err}")
        if conn: conn.rollback()
        audit_log("INSERT_ERROR", "anonymous", database, str(req.data),
                  f"MySQL {err.errno}: {err.msg}")

        friendly = f"MySQL {err.errno}: {err.msg}"
        if err.errno == 1062:
            friendly = f"Duplicate entry — a row with this value already exists. ({err.msg})"
        elif err.errno == 1452:
            friendly = f"Foreign key constraint failed — referenced row does not exist. ({err.msg})"
        elif err.errno == 1048:
            friendly = f"Column cannot be NULL. ({err.msg})"
        elif err.errno == 1292:
            friendly = f"Incorrect value for date/time/numeric column. ({err.msg})"

        return JSONResponse(status_code=400, content={"success": False, "error": friendly})

    except Exception as e:
        logger.error(f"[INSERT] Unexpected error: {e}", exc_info=True)
        if conn: conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

    finally:
        if conn and conn.is_connected():
            conn.close()