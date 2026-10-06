"""Probe how the SDK behaves with two differently-configured clients at once.

The wrapped engine reads its endpoints from module-level constants, so two clients
with different providers in one process may fight over the same globals. This
measures that rather than assuming it, and checks whether the exported endpoint
and key really are per-client.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))

from bookroom_sdk import Bookroom  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def main() -> int:
    print("=== per-client configuration is accepted ===")
    a = Bookroom(llm_api_key="KEY-A", jev_api_key="JEV-A",
                 llm_base_url="https://provider-a.example/v1",
                 llm_model="model-a",
                 jev_base_url="https://jev-a.example/v1", jev_model="jev-a")
    b = Bookroom(llm_api_key="KEY-B", jev_api_key="JEV-B",
                 llm_base_url="https://provider-b.example/v1",
                 llm_model="model-b",
                 jev_base_url="https://jev-b.example/v1", jev_model="jev-b")
    check("client A keeps its own endpoint and model",
          a.config.llm_base_url.endswith("provider-a.example/v1") and a.config.llm_model == "model-a")
    check("client B keeps its own endpoint and model",
          b.config.llm_base_url.endswith("provider-b.example/v1") and b.config.llm_model == "model-b")
    check("A and B review keys differ", a.config.jev_api_key == "JEV-A" and b.config.jev_api_key == "JEV-B")
    check("A and B review models differ", a.config.jev_model == "jev-a" and b.config.jev_model == "jev-b")

    print("\n=== describe() is secret-free for both ===")
    import json
    for client, name in ((a, "A"), (b, "B")):
        blob = json.dumps(client.describe())
        check(f"client {name} describe() leaks no key",
              "KEY-A" not in blob and "JEV-A" not in blob
              and "KEY-B" not in blob and "JEV-B" not in blob)
        check(f"client {name} describe() exports both endpoints",
              f"provider-{name.lower()}.example" in blob and f"jev-{name.lower()}.example" in blob)

    print("\n=== each client's call re-asserts its own configuration ===")
    a.load()  # first load puts the engine on sys.path
    from bookroom_sdk import bootstrap

    def engine_state(client) -> tuple[str, str, str, str]:
        # The supported path: resolve the module through the client's config.
        provider = bootstrap.module("gemini_provider", client.config)
        pipeline = bootstrap.module("book_pipeline", client.config)
        return (provider.BASE_URL, provider.MODEL,
                pipeline.JEV_BASE_URL, pipeline.JEV_MODEL)

    state_a = engine_state(a)
    check("client A runs against provider A",
          "provider-a.example" in state_a[0] and state_a[1] == "model-a"
          and "jev-a.example" in state_a[2] and state_a[3] == "jev-a", str(state_a))

    # Interleave: A, then B, then A again.
    state_b = engine_state(b)
    state_a2 = engine_state(a)
    check("interleaving A -> B -> A restores A",
          state_a2 == state_a,
          f"A={state_a2[1]} after B={state_b[1]}")
    check("B genuinely differed in between",
          state_b != state_a, f"B={state_b[1]}")
    check("B runs against provider B",
          "provider-b.example" in state_b[0] and state_b[1] == "model-b"
          and "jev-b.example" in state_b[2] and state_b[3] == "jev-b", str(state_b))
    check("A's config object is unchanged by B's use",
          a.config.llm_base_url.endswith("provider-a.example/v1"))
    check("keys are per-client and never cross over",
          a.config.llm_api_key == "KEY-A" and b.config.llm_api_key == "KEY-B"
          and a.config.jev_api_key == "JEV-A" and b.config.jev_api_key == "JEV-B")

    print(f"\nPASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name in FAILED:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
