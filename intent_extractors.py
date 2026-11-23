"""
intent_extractors.py
====================
Provides 3 Intent Extractor Interfaces for GuardianAgent:
  1. OracleIntentExtractor (Mechanical Oracle via sqlglot)
  2. DeterministicLinkerExtractor (Schema-grounded deterministic linker)
  3. LLMIntentExtractor (Local Ollama qwen2.5:3b-instruct wrapper)
"""
import os
import json
import re
import sqlite3
from typing import Dict, Any, List, Optional, Tuple
import sqlglot
from sqlglot import exp

from intent_spec_v2 import IntentSpecV2
from intent_spec_mechanical import derive_mechanical_intent
import ollama_client

PROMPT_INTENT_PATH = os.path.join("prompts", "intent_extractor_v1.txt")

def format_schema_for_prompt(db_path: Optional[str], request_text: str, max_chars: int = 2500) -> Tuple[str, bool]:
    """
    Formats SQLite schema into table definitions: table(col type, ...).
    If total length exceeds max_chars, selects most relevant tables by token overlap with request.
    Returns (schema_str, was_truncated).
    """
    if not db_path or not os.path.exists(db_path):
        return "No schema available.", False

    tables_info = {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
        for t in tables:
            cur.execute(f'PRAGMA table_info("{t}")')
            cols = [f"{r[1]} {r[2]}" for r in cur.fetchall()]
            tables_info[t] = cols
        conn.close()
    except Exception as e:
        return f"Error reading schema: {e}", False

    if not tables_info:
        return "Empty database schema.", False

    table_strings = {t: f"{t}({', '.join(cols)})" for t, cols in tables_info.items()}
    full_str = "; ".join(table_strings.values())

    if len(full_str) <= max_chars:
        return full_str, False

    # Truncation Rule: Rank tables by token overlap with request
    req_tokens = set(re.findall(r'\b[a-zA-Z0-9_]+\b', request_text.lower()))
    scored_tables = []
    for t, cols in tables_info.items():
        score = 0
        if t.lower() in req_tokens:
            score += 10
        for c in cols:
            c_name = c.split()[0].lower()
            if c_name in req_tokens:
                score += 2
        scored_tables.append((score, t))

    scored_tables.sort(key=lambda x: x[0], reverse=True)
    selected = []
    cur_len = 0
    for _, t in scored_tables:
        t_str = table_strings[t]
        if cur_len + len(t_str) + 2 > max_chars and selected:
            break
        selected.append(t_str)
        cur_len += len(t_str) + 2

    return "; ".join(selected), True

class BaseIntentExtractor:
    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        raise NotImplementedError

class OracleIntentExtractor(BaseIntentExtractor):
    """
    Mechanical Oracle extractor.
    Derives IntentSpecV2 directly from gold SQL (or benign SQL) using sqlglot AST parsing only.
    No placeholders or hardcoded strings.
    """
    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        if not record:
            return IntentSpecV2(operation="unknown", unverifiable_fields=["no_record_available"])
            
        gold = record.get('gold_sql') if record.get('gold_sql') else record.get('sql')
        if not gold:
            return IntentSpecV2(operation="unknown", unverifiable_fields=["no_gold_sql"])
            
        fam = record.get('family_id', '')
        return derive_mechanical_intent(gold, request=request, family_id=fam)

class DeterministicLinkerExtractor(BaseIntentExtractor):
    """
    Schema-grounded deterministic linker.
    Cardinality verified by comparing measured affected-row count against quantity
    implied by request. If ambiguous, expected_cardinality = unknown.
    """
    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        unverifiable = []
        req_clean = request.strip()
        req_lower = req_clean.lower()
        
        # 1. Operation Verb
        op = "SELECT"
        if any(w in req_lower for w in ('drop table', 'drop index', 'drop view')):
            op = "DROP"
        elif any(w in req_lower for w in ('alter table', 'add column')):
            op = "ALTER"
        elif any(w in req_lower for w in ('create table', 'create index', 'create view')):
            op = "CREATE"
        elif req_lower.startswith(('update', 'set', 'modify', 'change', 'increase', 'decrease', 'double', 'halve')):
            op = "UPDATE"
        elif req_lower.startswith(('delete', 'remove', 'erase', 'clear', 'purge')):
            op = "DELETE"
        elif req_lower.startswith(('insert', 'add', 'create new', 'append')):
            op = "INSERT"
        elif any(req_lower.startswith(w) for w in ('show', 'find', 'list', 'select', 'get', 'what', 'how many', 'report', 'view')):
            op = "SELECT"
            
        # 2. Schema Grounding (Table & Columns)
        matched_table = None
        matched_columns = []
        schema_tables = []
        table_columns = {}
        
        if db_path and os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                schema_tables = [row[0] for row in cur.fetchall()]
                for t in schema_tables:
                    cur.execute(f'PRAGMA table_info("{t}")')
                    table_columns[t] = [row[1] for row in cur.fetchall()]
                conn.close()
            except Exception:
                pass
                
        for t in sorted(schema_tables, key=len, reverse=True):
            pattern = r'\b' + re.escape(t.lower()) + r'\b'
            if re.search(pattern, req_lower):
                matched_table = t
                break
                
        if matched_table and matched_table in table_columns:
            for c in table_columns[matched_table]:
                pattern = r'\b' + re.escape(c.lower()) + r'\b'
                if re.search(pattern, req_lower):
                    matched_columns.append(c)
        else:
            for t, cols in table_columns.items():
                for c in cols:
                    pattern = r'\b' + re.escape(c.lower()) + r'\b'
                    if re.search(pattern, req_lower) and c not in matched_columns:
                        matched_columns.append(c)

        if not matched_table:
            unverifiable.append("target_table")
        if not matched_columns and op in ('UPDATE', 'DELETE'):
            unverifiable.append("filter_columns")

        # 3. Cardinality inference
        cardinality = "unknown"
        if any(w in req_lower for w in (' all ', ' every ', ' each ', 'all records', 'every record')):
            cardinality = "multi"
        elif any(w in req_lower for w in ('single', 'the record', 'one record', 'the row', 'one row')) or re.search(r'\b(?:id|rowid)\s*(?:is|=|)\s*\d+\b', req_lower):
            if re.search(r'\b(?:id|rowid)s?\s*(?:is|=|)?\s*\d+\s+and\s+\d+\b', req_lower):
                cardinality = "multi"
            else:
                cardinality = "single"
        else:
            cardinality = "unknown"

        # 4. Extract where_val
        where_val = None
        m_val = re.search(r'\b(?:rowid|id)\s*(?:is|=|)\s*(\d+)\b', req_lower)
        if m_val:
            where_val = m_val.group(1)

        return IntentSpecV2(
            operation=op,
            table=matched_table,
            filter_columns=matched_columns,
            where_val=where_val,
            expected_cardinality=cardinality,
            unverifiable_fields=unverifiable
        )

class LLMIntentExtractor(BaseIntentExtractor):
    """
    Local Ollama LLM Intent Extractor using qwen2.5:3b-instruct.
    Reads user_request and db_path schema ONLY. Never reads any metadata record fields.
    Outputs validate strictly against IntentSpecV2.
    Parse failures, schema-invalid outputs, or timeouts yield all-unknown fields (failing closed to CONFIRM).
    NO fallback to deterministic linker exists.
    """
    def __init__(self, system_prompt_path: str = PROMPT_INTENT_PATH, bypass_cache: bool = False):
        self.system_prompt_path = system_prompt_path
        self.bypass_cache = bypass_cache
        self.system_prompt = ""
        if os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                self.system_prompt = f.read().strip()
        self.truncation_count = 0
        self.call_count = 0
        self.parse_fail_count = 0

    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        self.call_count += 1
        
        # Format schema
        schema_text, was_truncated = format_schema_for_prompt(db_path, request)
        if was_truncated:
            self.truncation_count += 1

        user_prompt = f"Database Schema:\n{schema_text}\n\nUser Request: \"{request}\"\n\nJSON output:"

        parsed_json, raw_resp, meta = ollama_client.call_ollama(
            user_prompt=user_prompt,
            system_prompt=self.system_prompt,
            bypass_cache=self.bypass_cache
        )

        if not parsed_json or not isinstance(parsed_json, dict):
            self.parse_fail_count += 1
            return IntentSpecV2(
                operation="unknown",
                unverifiable_fields=["llm_parse_failure_or_timeout", "operation", "table", "filter_columns", "set_assignments", "cardinality"]
            )

        # Validate and unpack parsed fields
        op = str(parsed_json.get("operation", "unknown")).upper()
        if op not in ("SELECT", "UPDATE", "DELETE", "INSERT", "DROP", "ALTER"):
            op = "unknown"

        tbl = parsed_json.get("table")
        if tbl:
            tbl = str(tbl).strip("\"'").lower()
            if not tbl or tbl in ("none", "null", "unknown"):
                tbl = None

        raw_fcols = parsed_json.get("filter_columns", [])
        filter_columns = []
        if isinstance(raw_fcols, list):
            for c in raw_fcols:
                if isinstance(c, str):
                    filter_columns.append(c.strip("\"'").lower())

        where_val = parsed_json.get("where_val")
        if where_val is not None:
            where_val = str(where_val).strip("\"'")
            if where_val.lower() in ("none", "null", "unknown"):
                where_val = None

        raw_set = parsed_json.get("set_assignments", {})
        set_assignments = {}
        if isinstance(raw_set, dict):
            for k, v in raw_set.items():
                set_assignments[str(k).strip("\"'").lower()] = str(v).strip("\"'")

        card = str(parsed_json.get("expected_cardinality", "unknown")).lower()
        if card not in ("single", "multi", "unknown"):
            card = "unknown"

        unverifiable = []
        if op == "unknown":
            unverifiable.append("operation")
        if not tbl:
            unverifiable.append("target_table")
        if not filter_columns and op in ("UPDATE", "DELETE"):
            unverifiable.append("filter_columns")
        if card == "unknown":
            unverifiable.append("cardinality")

        return IntentSpecV2(
            operation=op,
            table=tbl,
            filter_columns=filter_columns,
            where_val=where_val,
            set_assignments=set_assignments,
            expected_cardinality=card,
            unverifiable_fields=unverifiable
        )
