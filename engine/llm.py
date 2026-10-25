"""Tiny provider-agnostic LLM client (Anthropic / OpenAI / Gemini) over plain HTTPS.

Configure ONE key via Streamlit secrets or env vars:
  ANTHROPIC_API_KEY  (default model claude-sonnet-4-5)
  OPENAI_API_KEY     (default model gpt-4.1-mini)
  GEMINI_API_KEY     (default model gemini-2.5-flash)
Optional: LLM_MODEL to override the model name.
"""
from __future__ import annotations

import json
import os
import re

import requests

DEFAULTS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4.1-mini", "gemini": "gemini-2.5-flash"}


def _secret(name):
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def provider():
    for p, k in (("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY")):
        if _secret(k):
            return p, _secret(k)
    return None, None


def available() -> bool:
    return provider()[0] is not None


def complete(system: str, messages: list[dict], json_mode=False, max_tokens=1500) -> str:
    """messages: [{'role': 'user'|'assistant', 'content': str}]"""
    p, key = provider()
    if not p:
        raise RuntimeError("No LLM API key configured.")
    model = _secret("LLM_MODEL") or DEFAULTS[p]
    if p == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system, "messages": messages,
                  "temperature": 0})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if p == "openai":
        body = {"model": model, "messages": [{"role": "system", "content": system}] + messages, "temperature": 0}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = requests.post("https://api.openai.com/v1/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {key}"}, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    # gemini
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                         for m in messages],
            "generationConfig": {"temperature": 0, **({"responseMimeType": "application/json"} if json_mode else {})}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      params={"key": key}, json=body, timeout=60)
    r.raise_for_status()
    return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])


def complete_json(system: str, messages: list[dict]) -> dict:
    last = ""
    for _ in range(2):
        last = complete(system, messages, json_mode=True)
        m = re.search(r"\{.*\}", last, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        messages = messages + [{"role": "assistant", "content": last},
                               {"role": "user", "content": "That was not valid JSON. Reply with the JSON object only."}]
    raise ValueError(f"Model did not return JSON: {last[:200]}")
