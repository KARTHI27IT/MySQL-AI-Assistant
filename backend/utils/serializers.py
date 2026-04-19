"""
utils/serializers.py
Pydantic request/response models shared across API routers.
"""
from typing import Any, Dict
from pydantic import BaseModel


class QueryRequest(BaseModel):
    database: str
    question: str
    use_schema_context: bool = True
    confirm_write: bool = False


class SchemaRefreshRequest(BaseModel):
    database: str
    force: bool = False


class RollbackRequest(BaseModel):
    operation_id: str


class InsertRequest(BaseModel):
    database: str
    table: str
    data: Dict[str, Any]