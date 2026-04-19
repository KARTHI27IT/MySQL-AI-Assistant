"""
api/query.py
Routes:
  POST /query          — Natural-language → SQL → execute
  POST /query/rollback — Undo a previous write operation
"""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import mysql.connector

from config import (
    ALLOW_WRITE_OPERATIONS, WRITE_TABLE_PREVIEW_LIMIT, ROLLBACK_TTL_SECONDS, MAX_ROLLBACK_ROWS
)
from core.cache import schema_cache
from core.database import (
    fetch_schema, get_db_connection, fetch_table_data, get_primary_key, execute_query
)
from core.rollback import rollback_history, build_rollback_sql
from agents.sql_generator import generate_sql
from agents.sql_validator import validate_sql_with_agent
from utils.sql_helpers import (
    classify_query, validate_write_sql, preview_write,
    capture_before_state, extract_table, format_schema
)
from utils.audit import audit_log
from utils.serializers import QueryRequest, RollbackRequest

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# POST /query
# ─────────────────────────────────────────────────────────────

@router.post("/query")
def query_db(req: QueryRequest):
    db         = req.database
    question   = req.question
    use_schema = req.use_schema_context
    confirm    = req.confirm_write

    logger.info(f"[QUERY] '{question}' | db={db} | confirm={confirm}")

    default = {
        "success": False, "error": None, "sql": None,
        "query_type": None, "requires_confirmation": False,
        "validation": {"valid": None, "reason": None, "attempts": 0},
    }

    # 1. Load schema
    schema = schema_cache.get(db)
    if not schema:
        try:
            schema = fetch_schema(db)
            schema_cache.set(db, schema)
        except Exception as e:
            return {**default, "error": f"Schema load failed: {e}"}

    # 2. Generate SQL
    sql, gen_err = generate_sql(question, schema, use_schema)
    if not sql:
        return {**default, "error": f"SQL generation failed: {gen_err}", "question": question}

    query_type = classify_query(sql)
    logger.info(f"[GEN] {sql[:100]} | type={query_type}")

    # 3. Block DDL / DCL
    if query_type.startswith("BLOCKED_") or query_type == "UNKNOWN":
        cmd = query_type.replace("BLOCKED_", "") if "BLOCKED_" in query_type else query_type
        return {
            **default, "sql": sql, "query_type": query_type,
            "error": f"Command blocked: {cmd}. Only SELECT/INSERT/UPDATE/DELETE allowed.",
        }

    # 4. Guard writes
    if query_type == "WRITE" and not ALLOW_WRITE_OPERATIONS:
        return {**default, "sql": sql, "query_type": "WRITE",
                "error": "Write operations are disabled on this server."}

    # 5. Validate SQL with agent
    schema_ctx = format_schema(schema) if use_schema else "Schema not provided"
    is_valid, v_reason, corrected_sql = validate_sql_with_agent(sql, question, schema_ctx)

    validation_info = {
        "valid": is_valid, "reason": v_reason,
        "original_sql": sql, "corrected_sql": corrected_sql, "attempts": 1,
    }

    if not is_valid:
        if corrected_sql:
            logger.info(f"[VALIDATOR] Auto-corrected: {corrected_sql[:80]}")
            sql = corrected_sql
            validation_info["used_correction"] = True
            validation_info["attempts"] = 2
        else:
            return {
                **default, "sql": sql, "query_type": query_type,
                "error": f"SQL validation failed: {v_reason}",
                "validation": validation_info,
                "suggestion": "Try rephrasing your question with more specific table/column names.",
            }

    # 6. Write safety check
    if query_type == "WRITE":
        ok, safety_msg = validate_write_sql(sql)
        if not ok:
            return {**default, "sql": sql, "query_type": "WRITE",
                    "error": f"Safety check failed: {safety_msg}",
                    "validation": validation_info}

    # 7. Write preview (requires confirmation)
    if query_type == "WRITE" and not confirm:
        preview = preview_write(sql, db)
        return {
            "requires_confirmation": True, "query_type": "WRITE", "sql": sql,
            "preview": preview, "validation": validation_info,
            "message": "Review the preview below and confirm to execute.",
            "success": False,
        }

    # 8. Execute
    conn = None
    try:
        conn = get_db_connection(db)
        before_data, pk_col, ai_col = [], None, None

        if query_type == "WRITE":
            table_name = extract_table(sql)
            if table_name and sql.lower().strip().startswith(('update', 'delete')):
                before_data, pk_col, ai_col = capture_before_state(
                    conn, sql, table_name,
                    sql.lower().split()[0],
                    max_rollback_rows=MAX_ROLLBACK_ROWS
                )

        success, result, err_msg = execute_query(conn, sql, query_type)

        if not success:
            conn.rollback()
            audit_log("ERROR", "anonymous", db, sql, f"FAILED: {err_msg}")
            return {**default, "sql": sql, "query_type": query_type,
                    "error": err_msg, "validation": validation_info}

        conn.commit()

        # READ result
        if query_type == "READ":
            logger.info(f"[READ] {result.get('row_count', 0)} rows")
            return {
                "success": True, "sql": sql, "query_type": "READ",
                "columns": result.get("columns", []),
                "result": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "validation": validation_info,
                "requires_confirmation": False,
            }

        # WRITE result
        table_name    = extract_table(sql)
        rows_affected = result.get("rows_affected", 0)
        ins_id        = result.get("last_insert_id")

        audit_log("WRITE", "anonymous", db, sql, f"OK rows={rows_affected}")

        table_data = None
        if table_name:
            table_data = fetch_table_data(conn, table_name, limit=WRITE_TABLE_PREVIEW_LIMIT)

        operation_id = None
        if table_name:
            op_prefix = sql.lower().strip().split()[0]
            if op_prefix in ('update', 'delete') and before_data:
                operation_id = rollback_history.add(
                    db, sql, before_data, table_name, op_prefix.upper(),
                    primary_key=pk_col, auto_increment_col=ai_col
                )
            elif op_prefix == 'insert' and ins_id:
                pk_col2, ai_col2 = get_primary_key(conn, table_name)
                if pk_col2:
                    cur2 = conn.cursor(dictionary=True)
                    cur2.execute(
                        f"SELECT * FROM `{table_name}` WHERE `{pk_col2}` = %s", (ins_id,)
                    )
                    ins_row = cur2.fetchone()
                    cur2.close()
                    if ins_row:
                        operation_id = rollback_history.add(
                            db, sql, [ins_row], table_name, "INSERT",
                            primary_key=pk_col2, auto_increment_col=ai_col2, inserted_id=ins_id
                        )

        rollback_exp = rollback_history.expires_in(operation_id) if operation_id else None

        return {
            "success": True, "sql": sql, "query_type": "WRITE",
            "rows_affected": rows_affected,
            "last_insert_id": ins_id,
            "table_name": table_name,
            "table_data": table_data or {},
            "operation_id": operation_id,
            "rollback_available": operation_id is not None,
            "rollback_expires_in": rollback_exp,
            "validation": validation_info,
            "requires_confirmation": False,
            "message": f"{sql.split()[0].upper()} executed — {rows_affected} row(s) affected",
        }

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        audit_log("ERROR", "anonymous", db, sql, f"MYSQL {err.errno}: {err.msg}")
        return {**default, "sql": sql, "query_type": query_type,
                "error": f"MySQL {err.errno}: {err.msg}", "validation": validation_info}
    except Exception as e:
        if conn: conn.rollback()
        audit_log("ERROR", "anonymous", db, sql, str(e))
        return {**default, "sql": sql, "query_type": query_type,
                "error": str(e), "validation": validation_info}
    finally:
        if conn and conn.is_connected():
            conn.close()


# ─────────────────────────────────────────────────────────────
# POST /query/rollback
# ─────────────────────────────────────────────────────────────

@router.post("/query/rollback")
def rollback_operation(req: RollbackRequest):
    logger.info(f"[ROLLBACK] Requested: {req.operation_id}")
    default = {"success": False, "error": None, "message": None, "table_data": None}

    operation = rollback_history.get(req.operation_id)
    if not operation:
        return {
            **default,
            "error": "Operation not found, already rolled back, or expired",
            "hint": f"Rollback window is {ROLLBACK_TTL_SECONDS}s",
        }

    rollback_sql, err = build_rollback_sql(operation)
    if err or not rollback_sql:
        return {**default, "error": err or "Could not generate rollback SQL"}

    logger.info(f"[ROLLBACK] SQL: {rollback_sql[:120]}")

    conn = None
    try:
        conn = get_db_connection(operation["database"])
        cursor = conn.cursor()
        cursor.execute("START TRANSACTION")
        for stmt in [s.strip() for s in rollback_sql.split(";") if s.strip()]:
            cursor.execute(stmt)
        conn.commit()
        cursor.close()
        rollback_history.mark_rolled_back(req.operation_id)
        audit_log("ROLLBACK", "anonymous", operation["database"], operation["sql"], "SUCCESS")

        table_data = fetch_table_data(
            conn, operation["table_name"], limit=WRITE_TABLE_PREVIEW_LIMIT
        )

        return {
            "success": True,
            "message": f"Rolled back {operation['operation_type']} on `{operation['table_name']}`",
            "original_sql":    operation["sql"],
            "rollback_sql":    rollback_sql,
            "table_name":      operation["table_name"],
            "table_data":      table_data or {},
            "rows_restored":   len(operation.get("before_data", [])),
            "operation_id":    req.operation_id,
        }

    except mysql.connector.Error as err:
        if conn: conn.rollback()
        audit_log("ROLLBACK_ERROR", "anonymous", operation["database"], rollback_sql, str(err))
        return {**default, "error": f"MySQL {err.errno}: {err.msg}"}
    except Exception as e:
        if conn: conn.rollback()
        return {**default, "error": str(e)}
    finally:
        if conn and conn.is_connected():
            conn.close()