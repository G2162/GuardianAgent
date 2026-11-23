"""
llm_judge.py
============
LLM-as-judge baseline using the same local Ollama model (qwen2.5:3b-instruct).
Inputs: request, candidate SQL, schema.
Outputs: {"decision": "ALLOW" | "CONFIRM" | "BLOCK", "reason": str}
Invalid output => CONFIRM.
"""
import os
import json
import sqlite3
from typing import Dict, Any, Optional

import ollama_client
from intent_extractors import format_schema_for_prompt

PROMPT_JUDGE_PATH = os.path.join("prompts", "judge_v1.txt")

class LLMJudge:
    def __init__(self, system_prompt_path: str = PROMPT_JUDGE_PATH, seed: int = 42, bypass_cache: bool = False):
        self.system_prompt_path = system_prompt_path
        self.seed = seed
        self.bypass_cache = bypass_cache
        self.system_prompt = ""
        if os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                self.system_prompt = f.read().strip()
        self.call_count = 0
        self.parse_fail_count = 0

    def judge(self, request: str, sql: str, db_path: Optional[str] = None) -> Dict[str, Any]:
        self.call_count += 1
        schema_text, _ = format_schema_for_prompt(db_path, request)

        user_prompt = (
            f"Database Schema:\n{schema_text}\n\n"
            f"User Request: \"{request}\"\n\n"
            f"Proposed SQL: \"{sql}\"\n\n"
            f"JSON Decision:"
        )

        options = {"seed": self.seed}
        parsed_json, raw_resp, meta = ollama_client.call_ollama(
            user_prompt=user_prompt,
            system_prompt=self.system_prompt,
            options=options,
            bypass_cache=self.bypass_cache
        )

        if not parsed_json or not isinstance(parsed_json, dict):
            self.parse_fail_count += 1
            return {
                "decision": "CONFIRM",
                "reason": "LLM judge parse failure or timeout (fail-closed default)",
                "raw_response": raw_resp,
                "metadata": meta
            }

        dec = str(parsed_json.get("decision", "CONFIRM")).upper().strip()
        if dec not in ("ALLOW", "CONFIRM", "BLOCK"):
            dec = "CONFIRM"

        reason = str(parsed_json.get("reason", "No reason provided"))

        return {
            "decision": dec,
            "reason": reason,
            "raw_response": raw_resp,
            "metadata": meta
        }
