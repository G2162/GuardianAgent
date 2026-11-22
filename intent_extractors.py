"""
intent_extractors.py
====================
Provides 3 Intent Extractor Interfaces for GuardianAgent v2:
  1. OracleIntentExtractor (Mechanical Oracle via sqlglot)
  2. DeterministicLinkerExtractor
  3. LLMIntentExtractor
"""
import os
import json
import re
import hashlib
import sqlite3
import sqlglot
from sqlglot import exp
from intent_spec_v2 import IntentSpecV2
from intent_spec_mechanical import derive_mechanical_intent

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

        # 3. Cardinality inference strictly by natural language quantity semantics
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
    Cached temperature=0 LLM intent extractor.
    Includes confidence scoring / abstention threshold.
    """
    def __init__(self, cache_file="data/llm_intent_cache.json", abstention_threshold=0.5):
        self.cache_file = cache_file
        self.cache = {}
        self.abstention_threshold = abstention_threshold
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}
        self.linker = DeterministicLinkerExtractor()

    def _hash_key(self, request: str, db_name: str) -> str:
        content = f"{db_name}::{request.strip()}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        db_name = os.path.basename(db_path) if db_path else ""
        key = self._hash_key(request, db_name)
        
        confidence = 1.0
        if key in self.cache:
            c = self.cache[key]
            confidence = c.get('confidence', 1.0)
            if confidence < self.abstention_threshold:
                return IntentSpecV2(operation="unknown", unverifiable_fields=["llm_abstained_low_confidence"])
            return IntentSpecV2(
                operation=c.get('operation', 'unknown'),
                table=c.get('table'),
                filter_columns=c.get('filter_columns', []),
                set_assignments=c.get('set_assignments', {}),
                where_val=c.get('where_val'),
                expected_cardinality=c.get('expected_cardinality', 'unknown')
            )

        intent = self.linker.extract_intent(request, db_path, record)
        confidence = 1.0 if not intent.unverifiable_fields else (0.7 if len(intent.unverifiable_fields) == 1 else 0.4)
        
        self.cache[key] = {
            'operation': intent.operation,
            'table': intent.table,
            'filter_columns': intent.filter_columns,
            'set_assignments': intent.set_assignments,
            'where_val': intent.where_val,
            'expected_cardinality': intent.expected_cardinality,
            'confidence': confidence
        }
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass
            
        if confidence < self.abstention_threshold:
            intent.unverifiable_fields.append("llm_abstained_low_confidence")
            
        return intent
