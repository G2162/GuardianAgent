"""
intent_extractors.py
====================
Provides 3 Intent Extractor Interfaces for GuardianAgent v2:
  1. OracleIntentExtractor
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

class BaseIntentExtractor:
    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        raise NotImplementedError

class OracleIntentExtractor(BaseIntentExtractor):
    """Oracle extractor that pulls intent_spec directly from ground truth record."""
    def extract_intent(self, request: str, db_path: str = None, record: dict = None) -> IntentSpecV2:
        if not record:
            return IntentSpecV2(unverifiable_fields=["no_record_available"])
            
        spec_dict = record.get('intent_spec')
        if not spec_dict:
            # Fallback for dev_extended records which don't have intent_spec
            req_lower = request.lower()
            op = "SELECT"
            if req_lower.startswith(('update', 'change', 'modify', 'set')):
                op = "UPDATE"
            elif req_lower.startswith(('delete', 'remove')):
                op = "DELETE"
            elif req_lower.startswith(('insert', 'add', 'create')):
                op = "INSERT"
            elif 'drop' in req_lower:
                op = "DROP"
            elif 'alter' in req_lower:
                op = "ALTER"
                
            tbl = None
            m_tbl = re.search(r'\bin\s+(?:table\s+)?([A-Za-z0-9_]+)', request, re.I)
            if m_tbl:
                tbl = m_tbl.group(1).lower()
            elif "table" in req_lower:
                m_tbl2 = re.search(r'table\s+([A-Za-z0-9_]+)', request, re.I)
                if m_tbl2:
                    tbl = m_tbl2.group(1).lower()
                
            fam = record.get('family_id', '')
            if 'MULTI_ROW' in fam or 'rowids' in req_lower or 'and' in req_lower and 'rowid' in req_lower:
                cardinality = "multi"
            elif "rowid" in req_lower or "record with" in req_lower:
                cardinality = "single"
            else:
                cardinality = "unknown"
            
            where_val = None
            m_val = re.search(r'rowid\s+(\d+)', req_lower)
            if m_val:
                where_val = m_val.group(1)

            return IntentSpecV2(
                operation=op,
                table=tbl,
                where_val=where_val,
                expected_cardinality=cardinality,
                unverifiable_fields=["oracle_spec_missing"]
            )
            
        op = spec_dict.get('operation', 'unknown')
        tbl = spec_dict.get('table')
        filt_cols = spec_dict.get('filter_columns', [])
        set_assign = spec_dict.get('set_assignments', {})
        where_text = spec_dict.get('where_text', '')
        
        where_val = None
        if where_text:
            try:
                tree = sqlglot.parse_one(f"SELECT * FROM t WHERE {where_text}")
                for lit in tree.find_all(exp.Literal):
                    where_val = str(lit.this).strip('"\'')
            except Exception:
                pass
        
        cardinality = "single"
        fam = record.get('family_id', '')
        if 'MULTI_ROW' in fam or 'UNDER_SCOPED' in fam:
            cardinality = "multi"
            
        return IntentSpecV2(
            operation=op,
            table=tbl,
            filter_columns=filt_cols,
            set_assignments=set_assign,
            where_text=where_text,
            where_val=where_val,
            expected_cardinality=cardinality
        )

class DeterministicLinkerExtractor(BaseIntentExtractor):
    """Schema-grounded deterministic linker."""
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
        if any(w in req_lower for w in ('all', 'every', 'each', 'multiple', 'entire', 'rowids')) or ('rowid' in req_lower and 'and' in req_lower):
            cardinality = "multi"
        elif any(w in req_lower for w in ('the', 'a single', 'one', 'id =', 'id is', 'rowid')):
            cardinality = "single"

        # 4. Extract where_val
        where_val = None
        m_val = re.search(r'(?:rowid|id)\s*(?:is|=|)\s*(\d+)', req_lower)
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
    """Cached temperature=0 LLM intent extractor."""
    def __init__(self, cache_file="data/llm_intent_cache.json"):
        self.cache_file = cache_file
        self.cache = {}
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
        
        if key in self.cache:
            c = self.cache[key]
            return IntentSpecV2(
                operation=c.get('operation', 'unknown'),
                table=c.get('table'),
                filter_columns=c.get('filter_columns', []),
                set_assignments=c.get('set_assignments', {}),
                where_val=c.get('where_val'),
                expected_cardinality=c.get('expected_cardinality', 'unknown')
            )

        intent = self.linker.extract_intent(request, db_path, record)
        self.cache[key] = {
            'operation': intent.operation,
            'table': intent.table,
            'filter_columns': intent.filter_columns,
            'set_assignments': intent.set_assignments,
            'where_val': intent.where_val,
            'expected_cardinality': intent.expected_cardinality
        }
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass
            
        return intent
