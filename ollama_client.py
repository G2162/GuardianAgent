"""
ollama_client.py
================
Thin wrapper for local Ollama server using requests only.

Features:
  - Reads OLLAMA_HOST (default http://localhost:11434) and OLLAMA_MODEL from environment.
  - Fixed options: temperature=0, seed=42, num_ctx=2048, num_predict=256, format='json'.
  - keep_alive='5m' so model unloads after run.
  - On-disk cache keyed by SHA-256 of (model tag + digest, system prompt, user prompt, options).
  - Retries with backoff on timeouts.
  - JSON parse validation; parse failures recorded, never crash run.
  - JSONL call log (results/llm_calls.jsonl).
  - Startup check (/api/tags and /api/show) writing results/llm_model_identity.json.
"""
import os
import sys
import json
import time
import hashlib
import requests
from typing import Dict, Any, Tuple, Optional

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")

CACHE_DIR = os.path.join("cache", "ollama")
LOG_PATH = os.path.join("results", "llm_calls.jsonl")
IDENTITY_PATH = os.path.join("results", "llm_model_identity.json")

# Fixed options
DEFAULT_OPTIONS = {
    "temperature": 0,
    "seed": 42,
    "num_ctx": 2048,
    "num_predict": 256
}

_MODEL_IDENTITY: Optional[Dict[str, Any]] = None

def get_model_identity() -> Dict[str, Any]:
    global _MODEL_IDENTITY
    if _MODEL_IDENTITY is not None:
        return _MODEL_IDENTITY

    os.makedirs("results", exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    # 1. GET /api/tags
    tag = OLLAMA_MODEL
    digest = "unknown"
    version = "unknown"
    param_size = "unknown"
    quant = "unknown"
    family = "unknown"

    try:
        r_version = requests.get(f"{OLLAMA_HOST}/api/version", timeout=5)
        if r_version.status_code == 200:
            version = r_version.json().get("version", "unknown")
    except Exception:
        pass

    try:
        r_tags = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if r_tags.status_code == 200:
            tags_data = r_tags.json().get("models", [])
            for m in tags_data:
                if m.get("name") == tag or m.get("model") == tag:
                    digest = m.get("digest", "unknown")
                    details = m.get("details", {})
                    param_size = details.get("parameter_size", "unknown")
                    quant = details.get("quantization_level", "unknown")
                    family = details.get("family", "unknown")
                    break
    except Exception as e:
        print(f"Warning: Failed to fetch /api/tags: {e}")

    # 2. POST /api/show
    try:
        r_show = requests.post(f"{OLLAMA_HOST}/api/show", json={"model": tag}, timeout=5)
        if r_show.status_code == 200:
            show_data = r_show.json()
            details = show_data.get("details", {})
            if details:
                param_size = details.get("parameter_size", param_size)
                quant = details.get("quantization_level", quant)
                family = details.get("family", family)
    except Exception as e:
        print(f"Warning: Failed to fetch /api/show: {e}")

    _MODEL_IDENTITY = {
        "model_tag": tag,
        "digest": digest,
        "parameter_size": param_size,
        "quantization": quant,
        "family": family,
        "ollama_version": version,
        "host": OLLAMA_HOST
    }

    with open(IDENTITY_PATH, "w", encoding="utf-8") as f:
        json.dump(_MODEL_IDENTITY, f, indent=2)

    return _MODEL_IDENTITY

def compute_cache_key(model_tag: str, digest: str, system_prompt: str, user_prompt: str, options: Dict[str, Any]) -> str:
    key_str = f"{model_tag}::{digest}::{system_prompt}::{user_prompt}::{json.dumps(options, sort_keys=True)}"
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

def call_ollama(
    user_prompt: str,
    system_prompt: str = "",
    options: Optional[Dict[str, Any]] = None,
    bypass_cache: bool = False,
    max_retries: int = 3,
    timeout_sec: int = 45,
    keep_alive: str = "5m"
) -> Tuple[Optional[Dict[str, Any]], str, Dict[str, Any]]:
    """
    Calls Ollama with JSON format.
    Returns:
        parsed_json: Optional[Dict[str, Any]] (None if parse failed)
        raw_response: str
        metadata: Dict[str, Any]
    """
    ident = get_model_identity()
    opts = dict(DEFAULT_OPTIONS)
    if options:
        opts.update(options)

    cache_key = compute_cache_key(ident["model_tag"], ident["digest"], system_prompt, user_prompt, opts)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # Check cache
    if not bypass_cache and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            # Log cache hit
            log_call({
                "timestamp": time.time(),
                "model": ident["model_tag"],
                "digest": ident["digest"],
                "options": opts,
                "prompt_hash": cache_key,
                "raw_response": cached_data.get("raw_response", ""),
                "latency_sec": 0.0,
                "cache_hit": True,
                "parse_ok": cached_data.get("parse_ok", False)
            })
            return cached_data.get("parsed_json"), cached_data.get("raw_response", ""), {"cache_hit": True, "prompt_hash": cache_key}
        except Exception:
            pass

    # Make request
    payload = {
        "model": ident["model_tag"],
        "prompt": user_prompt,
        "system": system_prompt,
        "stream": False,
        "format": "json",
        "options": opts,
        "keep_alive": keep_alive
    }

    raw_response = ""
    parsed_json = None
    parse_ok = False
    latency = 0.0
    err_msg = None

    eval_count = 0
    eval_duration = 0
    tokens_per_sec = 0.0

    for attempt in range(max_retries):
        t0 = time.perf_counter()
        try:
            resp = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=timeout_sec)
            latency = time.perf_counter() - t0
            if resp.status_code == 200:
                resp_json = resp.json()
                raw_response = resp_json.get("response", "")
                eval_count = resp_json.get("eval_count", 0)
                eval_duration = resp_json.get("eval_duration", 0)
                if eval_duration > 0:
                    tokens_per_sec = eval_count / (eval_duration / 1e9)
                try:
                    parsed_json = json.loads(raw_response)
                    parse_ok = True
                except Exception as je:
                    parse_ok = False
                    err_msg = f"JSONDecodeError: {je}"
                break
            else:
                err_msg = f"HTTP {resp.status_code}: {resp.text}"
                time.sleep(2 ** attempt)
        except requests.exceptions.Timeout:
            latency = time.perf_counter() - t0
            err_msg = "Timeout"
            time.sleep(2 ** attempt)
        except Exception as e:
            latency = time.perf_counter() - t0
            err_msg = str(e)
            time.sleep(2 ** attempt)

    # Save to disk cache
    cache_record = {
        "prompt_hash": cache_key,
        "raw_response": raw_response,
        "parsed_json": parsed_json,
        "parse_ok": parse_ok,
        "error": err_msg,
        "latency_sec": latency
    }
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_record, f, indent=2)
    except Exception:
        pass

    # Log to JSONL
    log_call({
        "timestamp": time.time(),
        "model": ident["model_tag"],
        "digest": ident["digest"],
        "options": opts,
        "prompt_hash": cache_key,
        "raw_response": raw_response,
        "latency_sec": latency,
        "cache_hit": False,
        "parse_ok": parse_ok,
        "error": err_msg
    })

    return parsed_json, raw_response, {"cache_hit": False, "prompt_hash": cache_key, "latency_sec": latency, "parse_ok": parse_ok}

def log_call(entry: Dict[str, Any]):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
