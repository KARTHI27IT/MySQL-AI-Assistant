"""
api/schema.py
Routes:
  GET  /schema/{database}   — Fetch (or serve from cache) the database schema
  POST /schema/refresh      — Force-refresh the schema cache for a database
"""
import logging

from fastapi import APIRouter

from core.cache import schema_cache
from core.database import fetch_schema
from utils.serializers import SchemaRefreshRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/schema/{database}")
def get_schema(database: str, use_cache: bool = True):
    """
    Return the schema for the given database.
    Served from in-memory cache when available (and use_cache=True).
    """
    try:
        if use_cache and (cached := schema_cache.get(database)):
            return {"schema": cached, "source": "cache"}
        schema = fetch_schema(database)
        schema_cache.set(database, schema)
        return {"schema": schema, "source": "fresh"}
    except ValueError as e:
        return {"error": str(e), "schema": None}
    except Exception as e:
        logger.error(f"get_schema: {e}")
        return {"error": str(e), "schema": None}


@router.post("/schema/refresh")
def refresh_schema(req: SchemaRefreshRequest):
    """
    Invalidate the cached schema for the given database and fetch fresh data.
    """
    try:
        schema_cache.invalidate(req.database)
        schema = fetch_schema(req.database)
        schema_cache.set(req.database, schema)
        return {
            "message":       f"Refreshed '{req.database}'",
            "tables":        len(schema["tables"]),
            "relationships": len(schema["relationships"]),
        }
    except Exception as e:
        return {"error": str(e)}