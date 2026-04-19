"""
agents/sql_generator.py
CrewAI agent that converts natural language questions into MySQL SQL.
"""
import logging
import time
from typing import Dict, Optional, Tuple

from crewai import Agent, Crew, Task

from config import llm, MAX_SQL_GEN_RETRIES, RETRY_BACKOFF_SECONDS
from utils.sql_helpers import extract_sql, valid_dml_prefix, format_schema

logger = logging.getLogger(__name__)


def generate_sql(
    question: str,
    schema: Dict,
    use_schema: bool,
    max_retries: int = MAX_SQL_GEN_RETRIES,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Use a CrewAI agent to generate a MySQL query from a natural-language question.

    Args:
        question:    The user's natural-language request.
        schema:      Parsed database schema dict.
        use_schema:  Whether to inject schema context into the prompt.
        max_retries: Number of additional attempts on failure.

    Returns:
        (sql_string, None)          on success
        (None, error_message)       on failure
    """
    schema_ctx = format_schema(schema) if use_schema and schema else "No schema provided."

    prompt = f"""You are a world-class MySQL query engine.

RULES — STRICTLY FOLLOW:
1. Output ONLY the SQL query — zero explanation, zero markdown, zero backticks
2. Always end with a semicolon
3. Use exact table/column names from the schema
4. Qualify column names with table aliases in multi-table queries
5. Always include a WHERE clause for UPDATE/DELETE

SCHEMA:
{schema_ctx}

USER REQUEST:
{question}

OUTPUT (SQL ONLY, ends with semicolon):"""

    for attempt in range(1, max_retries + 2):
        try:
            agent = Agent(
                role="Senior MySQL Engineer",
                goal="Convert natural language to production-ready SQL",
                backstory="Expert in complex multi-table queries and schema analysis.",
                llm=llm,
                verbose=False,
                allow_delegation=False,
            )
            task = Task(
                description=prompt,
                expected_output="A valid MySQL query ending with semicolon",
                agent=agent,
            )
            crew = Crew(agents=[agent], tasks=[task], verbose=False)
            raw  = str(crew.kickoff()).strip()
            sql  = extract_sql(raw)

            if sql and valid_dml_prefix(sql):
                logger.info(f"[GEN] attempt {attempt} success: {sql[:80]}")
                return sql, None

            logger.warning(f"[GEN] attempt {attempt} bad output: {raw[:80]}")

        except Exception as e:
            logger.error(f"[GEN] attempt {attempt} error: {e}")

        if attempt <= max_retries:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    return None, "SQL generation failed after all retries"