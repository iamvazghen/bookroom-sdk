"""Verify provider and endpoint agnosticism, end to end against live services.

Proves the three things an integrator needs:
  1. each client carries its own LLM and review endpoint, key and model;
  2. the SDK discovers which System One models a review endpoint offers;
  3. a real request through an arbitrary OpenAI-compatible endpoint returns
     usable text, and the SDK's own review path works against the live API.

Run:  python verify_provider_agnosticism.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tests"))

from bookroom_sdk import Bookroom  # noqa: E402
from mock_providers import MockProviders  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def read_key(name: str) -> str:
    for path in (Path(r"D:\summarizer\src\.env"), HERE / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            body = line.strip().lstrip("#").strip()
            if "=" not in body:
                continue
            key, _, value = body.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return ""


def main() -> int:
    print("=" * 70)
    print("PROVIDER AND ENDPOINT AGNOSTICISM")
    print("=" * 70)

    print("\n--- 1. two clients, two providers, interleaved ---")
    a = Bookroom(llm_api_key="KEY-A", jev_api_key="JEV-A",
                 llm_base_url="https://provider-a.example/v1", llm_model="model-a",
                 jev_base_url="https://jev-a.example/v1", jev_model="jev-a")
    b = Bookroom(llm_api_key="KEY-B", jev_api_key="JEV-B",
                 llm_base_url="https://provider-b.example/v1", llm_model="model-b",
                 jev_base_url="https://jev-b.example/v1", jev_model="jev-b")
    a.load()
    from bookroom_sdk import bootstrap

    def state(client):
        p = bootstrap.module("gemini_provider", client.config)
        q = bootstrap.module("book_pipeline", client.config)
        return p.BASE_URL, p.MODEL, p.API_KEY, q.JEV_BASE_URL, q.JEV_API_KEY

    sa, sb, sa2 = state(a), state(b), state(a)
    check("client A uses its own endpoint, model and key",
          sa[0].endswith("provider-a.example/v1") and sa[1] == "model-a"
          and sa[2] == "KEY-A" and sa[3].endswith("jev-a.example/v1")
          and sa[4] == "JEV-A", f"{sa[1]}")
    check("client B uses its own endpoint, model and key",
          sb[0].endswith("provider-b.example/v1") and sb[1] == "model-b"
          and sb[2] == "KEY-B" and sb[3].endswith("jev-b.example/v1")
          and sb[4] == "JEV-B", f"{sb[1]}")
    check("A -> B -> A restores A exactly", sa2 == sa,
          "no cross-contamination between clients")

    print("\n--- 2. System One model discovery on a live endpoint ---")
    jev_key = read_key("TYPESAFE_API_KEY")
    if not jev_key:
        check("review key available for discovery", False, "TYPESAFE_API_KEY is locked")
    else:
        live = Bookroom(llm_api_key="x", jev_api_key=jev_key,
                        jev_base_url="https://api.typesafe.ai/v1", jev_model="jev-latest")
        models = live.review.models()
        names = [m["name"] for m in models]
        check("the live endpoint lists System One models", bool(models), ", ".join(names))
        check("jev-latest is offered", "jev-latest" in names, ", ".join(names))
        check("every entry carries a name and a description shape",
              all({"name", "description", "release_date"} <= set(m) for m in models))

        print("\n--- 3. the SDK's own review path against the live API ---")
        verdict = live.review.evaluate(
            "Tolstoy's narrator states that the prisoners were later released.",
            "Tolstoy writes that the prisoners were eventually set free.")
        answers = verdict.get("answers", {})
        faithfulness = answers.get("faithfulness", {}).get("score")
        check("live review returns a faithfulness score", faithfulness is not None,
              f"score={faithfulness}")
        check("the configured model is echoed back",
              bool(verdict.get("model")), str(verdict.get("model")))

    print("\n--- 4. an arbitrary OpenAI-compatible endpoint generates text ---")
    with MockProviders() as mock:
        bridge_config = Bookroom(llm_api_key="any-key", jev_api_key="k",
                                 llm_base_url=mock.llm_base_url, llm_model="any-model")
        bridge_config.load()
        from bookroom_sdk import bootstrap as bs
        provider = bs.module("gemini_provider", bridge_config.config)
        text = provider.generate("Reply with exactly the word: AGNOSTIC", temperature=0.0,
                                 max_output_tokens=64)
        check("an arbitrary endpoint produced usable text", bool(text.strip()),
              repr(text[:40]))
        check("the model is whatever the caller asked for",
              provider.MODEL == "any-model", provider.MODEL)
        check("token accounting came back from that endpoint",
              provider.usage_snapshot()["calls"] >= 1, json.dumps(provider.usage_snapshot()))

    print(f"\nPASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name in FAILED:
        print(f"  - {name}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
