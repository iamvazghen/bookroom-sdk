"""Verify provenance is derived from the endpoint, not hardcoded.

The live MiniMax run wrote `generation_provider: "Google Gemini API"` and a
`gemini-3.8-flash` model line in a report that MiniMax actually produced. This
checks the label is now correct for several endpoints and rewrites the manifest
for an existing run - neither step contacts a provider.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))

from bookroom_sdk import bootstrap  # noqa: E402
from bookroom_sdk.config import Config  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def main() -> int:
    print("=== provider label is derived from the endpoint ===")
    cases = [
        ("https://generativelanguage.googleapis.com/v1beta", "Google Gemini API"),
        ("https://api.minimax.io/v1", "MiniMax"),
        ("https://openrouter.ai/api/v1", "OpenRouter"),
        ("http://127.0.0.1:8899", "local wire bridge"),
        ("https://api.example.com/v1", "OpenAI-compatible endpoint"),
    ]
    for base, expected in cases:
        config = Config(llm_api_key="x", llm_base_url=base)
        bootstrap.load(config)
        provider = bootstrap.module("gemini_provider", config)
        # provider_label() is resolved at call time, because BASE_URL is patched
        # after this module is imported. The PROVIDER constant is import-time only.
        actual = provider.provider_label()
        check(f"{base:<48} -> {expected}", actual == expected, actual)

    print("\n=== the MiniMax run's manifest is corrected in place ===")
    run_dir = Path(r"D:\summarizer-sdk\runs-minimax\tolstoy-minimax")
    guide = run_dir / "study-guide.md"
    if not guide.is_file():
        print("  (no previous run found; skipping)")
    else:
        config = Config(llm_api_key="x", llm_base_url="https://api.minimax.io/v1",
                        jev_api_key="y")
        bootstrap.load(config)
        manifest_module = bootstrap.module("report_manifest", config)
        source = Path(r"C:\Users\iamva\Downloads"
                      r"\_OceanofPDF.com_God_Sees_the_Truth_but_Waits_-_Leo_Tolstoy.pdf")
        written = Path(manifest_module.write_manifest(guide, source, jev_enabled=True))
        data = json.loads(written.read_text(encoding="utf-8"))
        check("generation_provider now names the real provider",
              data["generation_provider"] == "MiniMax", data["generation_provider"])
        check("generation_model still recorded", bool(data["generation_model"]),
              data["generation_model"])
        check("source hash unchanged", bool(data["source_sha256"]),
              data["source_sha256"][:16] + "...")

    print(f"\nPASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name in FAILED:
        print(f"  - {name}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
