"""
agents/sql_validator.py
CrewAI agent that validates a generated SQL query against the schema and user intent.
"""
import logging
import re
from typing import Optional, Tuple

from crewai import Agent, Crew, Task

from config import llm
from utils.sql_helpers import extract_sql, valid_dml_prefix

logger = logging.getLogger(__name__)


def validate_sql_with_agent(
    sql: str,
    question: str,
    schema_ctx: str,
) -> Tuple[bool, str, Optional[str]]:
    """
    Use a CrewAI agent to validate a SQL query for correctness, safety,
    and alignment with the user's intent.

    Args:
        sql:        The candidate SQL query.
        question:   The original natural-language question.
        schema_ctx: Formatted schema string.

    Returns:
        (is_valid, reason, corrected_sql)
        - is_valid:      True if the query passes all checks.
        - reason:        One-sentence explanation.
        - corrected_sql: A fixed query if is_valid is False, else None.
    """
    prompt = f"""You are a strict SQL Validator for MySQL.

Given the user's question, the database schema, and a candidate SQL query, you must:
1. Check MySQL syntax correctness
2. Verify ALL table names exist in the schema
3. Verify ALL column names exist in their respective tables
4. Verify the query logically matches the user's intent
5. Check UPDATE/DELETE always has WHERE clause
6. Check for obvious logic errors (wrong JOIN conditions, incorrect comparisons)

DATABASE SCHEMA:
{schema_ctx}

USER'S ORIGINAL QUESTION:
{question}

CANDIDATE SQL QUERY:
{sql}

Respond in EXACTLY this format — no other text:
VALID: <YES or NO>
REASON: <one concise sentence>
CORRECTED_SQL: <corrected SQL if NO, else NONE>

Do not add any explanation outside this format."""

    try:
        agent = Agent(
            role="MySQL SQL Validator",
            goal="Validate SQL queries for correctness, safety, and alignment with user intent",
            backstory="You are a meticulous DBA who catches every SQL mistake before it runs.",
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )
        task = Task(
            description=prompt,
            expected_output="Validation result in the specified format",
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        raw  = str(crew.kickoff()).strip()
        logger.info(f"[VALIDATOR] Raw output: {raw[:200]}")

        valid_match   = re.search(r'VALID:\s*(YES|NO)',              raw, re.IGNORECASE)
        reason_match  = re.search(r'REASON:\s*(.+?)(?:\n|CORRECTED_SQL:|$)', raw, re.IGNORECASE | re.DOTALL)
        correct_match = re.search(r'CORRECTED_SQL:\s*(.+?)(?:;?\s*$)',       raw, re.IGNORECASE | re.DOTALL)

        is_valid  = bool(valid_match and valid_match.group(1).upper() == "YES")
        reason    = reason_match.group(1).strip() if reason_match else "Validation response unclear"
        corrected = None

        if not is_valid and correct_match:
            raw_corr = correct_match.group(1).strip()
            if raw_corr.upper() not in ("NONE", "N/A", ""):
                corrected = extract_sql(raw_corr) or (raw_corr if valid_dml_prefix(raw_corr) else None)

        logger.info(f"[VALIDATOR] valid={is_valid} reason={reason}")
        return is_valid, reason, corrected

    except Exception as e:
        logger.error(f"[VALIDATOR] Agent error: {e}")
        return True, f"Validator unavailable ({e}), proceeding", None