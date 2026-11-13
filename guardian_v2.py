"""
guardian_v2.py
==============
GuardianAgent v2 Pipeline.

Architecture:
  Layer 1: Intent-Free Structural Rules (sqlglot AST checks, tautology folding, stacked queries, DDL, hidden writes).
  Layer 2: Effect Check in rolled-back transaction (executes_ok, n_matched, n_changed, schema_changed, 500ms timeout).
  Layer 3: IntentSpec v2 comparison (table, columns, values, cardinality, modality).

Configurable parameters:
  - layer: 1, 2, or 3 (for ablation studies)
  - risk_mode: 'rules' (deterministic mapping from labeling_policy.json) or 'weighted' (score-based)
  - extractor: 'oracle', 'linker', or 'llm'
  - variant: 'variant_a' (exact single delete ALLOW) or 'variant_b' (all deletes CONFIRM)
"""
import os
import time
from guardian_layer1 import check_layer1_rules
from guardian_layer2 import check_layer2_effect
from intent_spec_v2 import extract_sql_components, compare_intent_and_sql, IntentSpecV2
from intent_extractors import OracleIntentExtractor, DeterministicLinkerExtractor, LLMIntentExtractor

# Registry of extractors
EXTRACTORS = {
    'oracle': OracleIntentExtractor(),
    'linker': DeterministicLinkerExtractor(),
    'llm': LLMIntentExtractor()
}

def guardian_check_v2(
    user_request: str,
    sql_str: str,
    db_path: str = None,
    record: dict = None,
    layer: int = 3,
    risk_mode: str = "rules",
    extractor: str = "oracle",
    variant: str = "variant_a",
    timeout_ms: int = 500
):
    """
    Evaluates candidate SQL through the GuardianAgent v2 Pipeline.

    Returns dict:
      decision: 'ALLOW' | 'CONFIRM' | 'BLOCK'
      risk_score: float (0 - 100)
      reasons: list of str
      layer_fired: int (1, 2, or 3)
      is_catastrophic: bool
      is_timeout: bool
      elapsed_ms: float
      n_matched: int
      n_changed: int
    """
    start_time = time.perf_counter()
    reasons = []
    
    # -------------------------------------------------------------
    # Layer 1: Intent-Free Structural Rules
    # -------------------------------------------------------------
    req_clean = user_request.strip() if user_request else ""
    is_violation, rule_id, l1_decision, is_catastrophic = check_layer1_rules(sql_str, req_clean)
    
    if is_violation:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return {
            'decision': l1_decision,
            'risk_score': 100.0 if l1_decision == 'BLOCK' else 50.0,
            'reasons': [rule_id],
            'layer_fired': 1,
            'is_catastrophic': is_catastrophic,
            'is_timeout': False,
            'elapsed_ms': elapsed,
            'n_matched': 0,
            'n_changed': 0
        }

    if layer == 1:
        # Layer 1 ablation: if passed L1, return ALLOW (or CONFIRM on write if conservative)
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return {
            'decision': 'ALLOW',
            'risk_score': 0.0,
            'reasons': ["Passed Layer 1 structural rules"],
            'layer_fired': 1,
            'is_catastrophic': False,
            'is_timeout': False,
            'elapsed_ms': elapsed,
            'n_matched': 0,
            'n_changed': 0
        }

    # -------------------------------------------------------------
    # Layer 2: Effect Check (Rolled-back transaction)
    # -------------------------------------------------------------
    effects = {
        'executes_ok': True,
        'error_message': None,
        'n_matched': 0,
        'n_changed': 0,
        'schema_changed': False,
        'is_timeout': False,
        'elapsed_ms': 0.0,
        'decision': None,
        'reason': None
    }
    
    if db_path and os.path.exists(db_path):
        effects = check_layer2_effect(db_path, sql_str, timeout_ms=timeout_ms)
        
        # Check timeout or execution error on write
        if effects.get('decision') == 'CONFIRM':
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return {
                'decision': 'CONFIRM',
                'risk_score': 75.0,
                'reasons': [effects.get('reason', 'Layer 2 execution failure or timeout')],
                'layer_fired': 2,
                'is_catastrophic': False,
                'is_timeout': effects.get('is_timeout', False),
                'elapsed_ms': elapsed,
                'n_matched': effects.get('n_matched', 0),
                'n_changed': effects.get('n_changed', 0)
            }
            
    if layer == 2:
        # Layer 2 ablation
        n_matched = effects.get('n_matched', 0)
        n_changed = effects.get('n_changed', 0)
        sql_comp = extract_sql_components(sql_str)
        if sql_comp['operation'] == 'DELETE' and variant == 'variant_b':
            dec = 'CONFIRM'
        elif n_matched > 1 or n_changed > 1:
            dec = 'CONFIRM'
        else:
            dec = 'ALLOW'
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return {
            'decision': dec,
            'risk_score': 30.0 if dec == 'CONFIRM' else 0.0,
            'reasons': ["Layer 2 effect evaluation"],
            'layer_fired': 2,
            'is_catastrophic': False,
            'is_timeout': False,
            'elapsed_ms': elapsed,
            'n_matched': n_matched,
            'n_changed': n_changed
        }

    # -------------------------------------------------------------
    # Layer 3: Intent Comparison (IntentSpec v2)
    # -------------------------------------------------------------
    ext = EXTRACTORS.get(extractor, EXTRACTORS['oracle'])
    intent_spec = ext.extract_intent(user_request, db_path=db_path, record=record)
    sql_comp = extract_sql_components(sql_str)
    
    comp_res = compare_intent_and_sql(
        intent=intent_spec,
        sql_comp=sql_comp,
        measured_effects=effects,
        risk_mode=risk_mode,
        variant=variant
    )
    
    elapsed = (time.perf_counter() - start_time) * 1000.0
    return {
        'decision': comp_res['decision'],
        'risk_score': comp_res['risk_score'],
        'reasons': comp_res['reasons'],
        'layer_fired': 3,
        'is_catastrophic': False,
        'is_timeout': False,
        'elapsed_ms': elapsed,
        'n_matched': effects.get('n_matched', 0),
        'n_changed': effects.get('n_changed', 0)
    }

