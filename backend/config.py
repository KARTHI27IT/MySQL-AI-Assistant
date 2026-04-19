import os
from dotenv import load_dotenv
from crewai import LLM

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Feature Flags & Limits
# ─────────────────────────────────────────────────────────────
ALLOW_WRITE_OPERATIONS    = os.getenv("ALLOW_WRITE_OPERATIONS", "true").lower() == "true"
MAX_EXECUTION_TIME_MS     = int(os.getenv("MAX_EXECUTION_TIME_MS", "30000"))
AUDIT_LOG_FILE            = os.getenv("AUDIT_LOG_FILE", "./logs/audit.log")
WRITE_TABLE_PREVIEW_LIMIT = int(os.getenv("WRITE_TABLE_PREVIEW_LIMIT", "100"))
ROLLBACK_TTL_SECONDS      = int(os.getenv("ROLLBACK_TTL_SECONDS", "300"))
MAX_RETRY_ATTEMPTS        = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
RETRY_BACKOFF_SECONDS     = float(os.getenv("RETRY_BACKOFF_SECONDS", "1.0"))
MAX_SQL_GEN_RETRIES       = int(os.getenv("MAX_SQL_GEN_RETRIES", "2"))
MAX_ROLLBACK_ROWS         = int(os.getenv("MAX_ROLLBACK_ROWS", "1000"))

os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)

# ─────────────────────────────────────────────────────────────
# MySQL Connection Config
# ─────────────────────────────────────────────────────────────
MYSQL_CONFIG = {
    "host":       os.getenv("MYSQL_HOST", "localhost"),
    "user":       os.getenv("MYSQL_USER", "root"),
    "password":   os.getenv("MYSQL_PASSWORD", ""),
    "port":       int(os.getenv("MYSQL_PORT", "3306")),
    "autocommit": False,
}

# ─────────────────────────────────────────────────────────────
# LLM (CrewAI)
# ─────────────────────────────────────────────────────────────
llm = LLM(
    model=os.getenv("GROQ_MODEL", "groq/llama-3.1-8b-instant"),
    api_key=os.getenv("GROQ_API_KEY")
)