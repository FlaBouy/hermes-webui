#!/usr/bin/env python3
"""
rag_config.py — single source of truth for Jarvis RAG model + retrieval config.
Created 2026-06-20 per GUI Mods_V3 item #1.

Both jarvis_rag_poc.py and smedley-rag-api.py import from here so model names and
retrieval params live in ONE place — no more duplicate CHAT_MODEL definitions
drifting between files ("Past Rick ambushes Future Rick").

Nothing here runs at import time. ensure_model_loaded() is called explicitly
(e.g. at API startup) so importing this module has zero side effects.
"""
import json
import subprocess
import urllib.request

# ---------- models ----------
CHAT_MODEL_FAST = "qwen/qwen3-14b"      # fast lookups: part numbers, simple specs, voice
CHAT_MODEL_DEEP = "qwen/qwen3.6-27b"    # project docs, Brewton specs, NEC, design review
DEFAULT_MODEL   = CHAT_MODEL_DEEP       # 27B is the default answer model (GUI Mods_V3 #2)

EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
COLLECTION  = "jarvis_kb"

# ---------- retrieval params (fast vs deep) ----------
TOPK_FAST       = 6
TOPK_DEEP       = 10
MAX_CHUNK_FAST  = 700
MAX_CHUNK_DEEP  = 1000

# ---------- LM Studio ----------
LMS_BASE         = "http://127.0.0.1:1234/v1"
LMS_LOAD_TIMEOUT = 600   # seconds; a cold 27B load can be slow


def loaded_models(timeout=5):
    """Return the set of model ids currently loaded in LM Studio, or None if unreachable."""
    try:
        with urllib.request.urlopen(LMS_BASE + "/models", timeout=timeout) as r:
            data = json.loads(r.read())
        return {m.get("id", "") for m in data.get("data", [])}
    except Exception:
        return None


def _is_loaded(model, models):
    if not models:
        return False
    return any(model in m for m in models)


def ensure_model_loaded(model):
    """Best-effort: make `model` available in LM Studio with NO manual tee-up.

    Returns (model_to_use, note):
      - (model, "")                 model is loaded / was loaded successfully
      - (fallback, "reason")        model couldn't be loaded; using a loaded fallback
      - (model, "lms unreachable")  LM Studio itself is unreachable (caller decides)

    Intended for startup use so the first real query is warm. Never raises.
    """
    models = loaded_models()
    if models is None:
        return model, "lms unreachable"
    if _is_loaded(model, models):
        return model, ""

    # Try to load it via the LM Studio CLI. If `lms` isn't on PATH, fall through.
    try:
        subprocess.run(["lms", "load", model, "-y"],
                       capture_output=True, text=True, timeout=LMS_LOAD_TIMEOUT)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    models = loaded_models()
    if _is_loaded(model, models):
        return model, ""

    # Could not load — degrade gracefully to a loaded chat model if one exists.
    if models:
        for cand in (CHAT_MODEL_DEEP, CHAT_MODEL_FAST):
            if _is_loaded(cand, models):
                return cand, "requested %s unavailable; using %s" % (model, cand)
        for m in models:
            if EMBED_MODEL not in m and m:
                return m, "requested %s unavailable; using %s" % (model, m)
    return model, "no chat model loaded"
