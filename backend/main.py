from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import sys, codecs, os, logging

# ─────────────────────────────────────────────────────────────
# UTF-8 Fix for Windows
# ─────────────────────────────────────────────────────────────
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, errors='replace')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, errors='replace')
    os.environ['PYTHONUTF8'] = '1'

os.makedirs('./logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('./logs/app.log', encoding='utf-8', errors='replace'),
        logging.StreamHandler()
    ]
)

from api.query import router as query_router
from api.schema import router as schema_router
from api.insert import router as insert_router
from core.database import get_base_connection
from core.cache import schema_cache
from core.rollback import rollback_history
from config import ALLOW_WRITE_OPERATIONS, ROLLBACK_TTL_SECONDS, MAX_ROLLBACK_ROWS

# ─────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="MySQL AI Assistant", version="7.1-InsertModal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────
app.include_router(query_router)
app.include_router(schema_router)
app.include_router(insert_router)


# ─────────────────────────────────────────────────────────────
# Root & Health
# ─────────────────────────────────────────────────────────────
@app.get("/")
def home():
    return {
        "version": "7.1-InsertModal",
        "features": [
            "SQL Generator", "SQL Validator Agent", "Manual Insert Modal",
            "Rollback (UPDATE/DELETE/INSERT)", "Write Preview",
            "Schema Cache", "Audit Log"
        ],
        "writes_enabled": ALLOW_WRITE_OPERATIONS,
        "rollback_ttl": ROLLBACK_TTL_SECONDS,
    }


@app.get("/databases")
def get_databases():
    import mysql.connector
    try:
        conn = get_base_connection()
        cur  = conn.cursor()
        cur.execute("SHOW DATABASES")
        dbs  = [d[0] for d in cur.fetchall()
                if d[0] not in ('information_schema', 'performance_schema', 'mysql', 'sys')]
        cur.close()
        conn.close()
        return {"databases": dbs}
    except Exception as e:
        return {"databases": [], "error": str(e)}


@app.get("/health")
def health():
    import mysql.connector
    try:
        conn = get_base_connection()
        conn.close()
        return {
            "status": "healthy",
            "mysql": "connected",
            "schema_cache_size": len(schema_cache.cache),
            "rollback_history_size": len(rollback_history.history),
            "writes_enabled": ALLOW_WRITE_OPERATIONS,
            "rollback_ttl_seconds": ROLLBACK_TTL_SECONDS,
            "max_rollback_rows": MAX_ROLLBACK_ROWS,
            "version": "7.1-InsertModal"
        }
    except Exception as e:
        return {"status": "unhealthy", "mysql": "disconnected", "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Global Exception Handler
# ─────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exc(request: Request, exc: Exception):
    import logging
    logging.getLogger(__name__).error(f"[UNHANDLED] {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": str(exc),
            "requires_confirmation": False,
            "query_type": None
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")