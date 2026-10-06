"""Optional Jev typed evaluation adapter for book summaries."""

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

ENABLED = os.getenv("JEV_ENABLED", "false").lower() == "true"
API_KEY = os.getenv("TYPESAFE_API_KEY", "")
BASE_URL = os.getenv("JEV_BASE_URL", "https://api.typesafe.ai/v1").rstrip("/")
MODEL = os.getenv("JEV_MODEL", "jev-latest")


def evaluate_summary(source_excerpt: str, summary: str) -> dict:
    """Score faithfulness, coverage, and clarity against a bounded excerpt.

    The scores are advisory signals, not proof of correctness. Use source
    excerpts rather than sending an entire book in one request.
    """
    if not ENABLED:
        raise RuntimeError("Jev is disabled; set JEV_ENABLED=true to use it")
    if not API_KEY:
        raise ValueError("Set TYPESAFE_API_KEY in the local environment")
    response = httpx.post(
        f"{BASE_URL}/systemone",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "state": {"source_excerpt": source_excerpt, "summary": summary},
            "questions": {
                "faithfulness": {
                    "type": "score",
                    "instructions": "Rate whether the summary's claims are supported by the source. Penalize invented details.",
                    "criteria": ["Unsupported or misleading", "Mostly unsupported", "Mixed support", "Mostly supported", "Directly and accurately supported"],
                },
                "coverage": {
                    "type": "score",
                    "instructions": "Rate whether the summary captures the source's central ideas without important omissions.",
                    "criteria": ["Misses the central idea", "Major omissions", "Some key ideas covered", "Nearly all key ideas covered", "All central ideas represented concisely"],
                },
                "clarity": {
                    "type": "score",
                    "instructions": "Rate readability for a general reader.",
                    "criteria": ["Unclear", "Hard to follow", "Understandable with effort", "Clear", "Exceptionally clear and concise"],
                },
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
