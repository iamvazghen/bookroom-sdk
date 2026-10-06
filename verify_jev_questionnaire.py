"""A worked JEv questionnaire: what to ask, and why it gives decision-ready answers.

Three rounds against the real TypeSafe API, using the Bookroom release as the
state because the answers are then actionable rather than illustrative.

  Round 1  eleven questions in ONE request - every primitive, every format
  Round 2  a follow-up whose question set depends on a round-1 answer
  Round 3  the same judgment asked two ways: vague, then distilled

Run:  python verify_jev_questionnaire.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = Path(r"D:\summarizer\src\.env")
MODEL = "jev-latest"
BASE = "https://api.typesafe.ai/v1/systemone"

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def api_key() -> str:
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("TYPESAFE_API_KEY="):
            return raw.split("=", 1)[1].strip()
    raise SystemExit("TYPESAFE_API_KEY not found")


def call(state: object, questions: dict, key: str) -> dict:
    body = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode()
    request = urllib.request.Request(BASE, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {key}")
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Jev HTTP {exc.code}: {exc.read().decode()[:400]}") from None
    payload["_elapsed"] = round(time.time() - started, 2)
    return payload


def spread(probabilities: dict[str, float]) -> float:
    """Top-two probability gap: how decisive the distribution is."""
    values = sorted(probabilities.values(), reverse=True)
    return round(values[0] - values[1], 3) if len(values) > 1 else round(values[0], 3)


def show(label: str, answer: dict) -> None:
    kind = answer.get("type")
    if kind == "noul":
        print(f"    {label:<28} noul={answer['noul']:.3f}")
    elif kind == "choice":
        top = answer["probabilities"]
        ranked = sorted(top.items(), key=lambda kv: -kv[1])
        print(f"    {label:<28} choice={answer['choice']}  "
              f"conf={answer['confidence']:.3f}  spread={spread(top):.3f}")
        print(f"      {'  '.join(f'{k}={v:.2f}' for k, v in ranked)}")
    elif kind == "score":
        print(f"    {label:<28} score={answer['score']:.2f}  "
              f"conf={answer['confidence']:.3f}  spread={spread(answer['probabilities']):.3f}")
        ranked = sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])
        print(f"      {'  '.join(f'L{k}={v:.2f}' for k, v in ranked)}")


# --------------------------------------------------------------------------- #
STATE = {
    "project": "bookroom-sdk",
    "release": {
        "version": "2.0.0",
        "license": "MIT",
        "registry_status": {
            "pypi": "unpublished",
            "npm": "unpublished",
        },
    },
    "artifacts": [
        {"name": "bookroom_sdk-2.0.0-py3-none-any.whl", "exists": True, "engine_files": 20},
        {"name": "bookroom_sdk-2.0.0.tar.gz", "exists": True, "engine_files": 20},
        {"name": "bookroom-sdk-2.0.0.tgz", "exists": True, "engine_files": 20},
    ],
    "verification": {
        "python": {"suites": 4, "checks": 181, "failures": 0},
        "node": {"suites": 1, "checks": 41, "failures": 0},
        "ci": {"jobs": 9, "passing": 9, "failing": 0},
    },
    "providers": {
        "llm": {"name": "gemini-3.8-flash", "status": "quota_exhausted", "retry_after_seconds": 17817},
        "review": {"name": "jev-1.13.0", "status": "ok"},
    },
    "readme": {
        "install_commands": [
            {"command": 'pip install "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"',
             "status": "verified"},
            {"command": "pip install bookroom-sdk",
             "status": "unpublished_404"},
        ],
    },
}


ROUND_1 = {
    # --- Choice: routing, with rubrics and a no-match option ----------------
    "release_blocker": {
        "type": "choice",
        "instructions": "Which single item most urgently blocks a usable public release?",
        "criteria": {
            "registry_missing": "Install commands that do not work yet because nothing is published.",
            "live_run_unproven": "No end-to-end run has completed against real providers.",
            "ci_red": "Automated checks are failing.",
            "none_of_the_above": "Nothing listed is a genuine blocker.",
        },
    },
    # --- Choice: closed set with an escape hatch -----------------------------
    "book_format": {
        "type": "choice",
        "instructions": "Which input format is this release primarily built to accept?",
        "criteria": {
            "pdf": "Documents that may be scanned or paginated.",
            "epub": "Reflowable digital books.",
            "both_equally": "Both are first-class and equally supported.",
            "other": "Something not listed.",
        },
    },
    # --- Noul: checkable fact, expected decisive ---------------------------
    "engine_is_self_contained": {
        "type": "noul",
        "instructions": "Do all three entries in `artifacts` report that the engine is bundled inside them?",
    },
    # --- Noul: structured criteria (true/false meaning spelled out) ----------
    "ci_is_green": {
        "type": "noul",
        "instructions": "Is every automated check currently passing?",
        "criteria": {
            "true": "All checks in `verification` report zero failures.",
            "false": "At least one check reports a failure.",
        },
    },
    # --- Noul: path reference into a nested list ---------------------------
    "live_providers_unavailable": {
        "type": "noul",
        "instructions": "Is `providers.llm.status` not equal to 'ok'?",
    },
    # --- Noul: one per label, combined in code later -----------------------
    "blocker_is_registry": {
        "type": "noul",
        "instructions": "Is `release.registry_status.pypi` equal to 'unpublished'?",
    },
    "blocker_is_quota": {
        "type": "noul",
        "instructions": "Is `providers.llm.status` equal to 'quota_exhausted'?",
    },
    # --- Score: concrete levels, not vibes ---------------------------------
    "release_readiness": {
        "type": "score",
        "instructions": "How close is this release to being installable and demonstrable by a stranger?",
        "criteria": [
            "Not installable by anyone outside this machine.",
            "Installable from a checkout, but a published install does not work.",
            "Installable from a public URL, with a documented command that fails.",
            "Installable from a public URL, with every documented command verified working.",
            "Installable from a public registry, with a full run demonstrated live.",
        ],
    },
    # --- Score: structured object instructions (tests that format) ---------
    "readme_accuracy": {
        "type": "score",
        "instructions": {
            "command_in_issue": "One or more documented commands are known not to work.",
            "command": "The install command a reader would copy first.",
            "evidence": "`readme.install_commands`",
        },
        "criteria": [
            "Every documented command is verified to work.",
            "One command is documented but does not work; another command is verified.",
            "The primary documented command does not work.",
        ],
    },
    # --- Noul: deliberately unanswerable, to observe calibration -----------
    "will_users_pay_for_it": {
        "type": "noul",
        "instructions": "Will enough people pay for this product that it sustains its costs?",
    },
    # --- Noul: hallucination guard (the negation pair) ----------------------
    "claim_supported": {
        "type": "noul",
        "instructions": "Does `verification.ci.passing` equal `verification.ci.jobs`?",
    },
    "claim_contradicted": {
        "type": "noul",
        "instructions": "Does `verification.python.failures` exceed zero?",
    },
}

ROUND_3_VAGUE = {
    "vague_readiness": {
        "type": "noul",
        "instructions": "Is it ready?",
    },
    "vague_quality": {
        "type": "noul",
        "instructions": "Is the code good?",
    },
    "distilled_install_works": {
        "type": "noul",
        "instructions": "Can a user who has never seen this machine install the package using a command copied verbatim from the README?",
    },
    "distilled_bounded_by_quota": {
        "type": "noul",
        "instructions": "Is any verification result in this state derived from a successful live call to a real provider, rather than a mock?",
    },
}


ROUND_4_SCOPED = {
    # Round 3's questions had better vocabulary but still an ambiguous SCOPE:
    # "a command" when the state holds two with different statuses, and "any
    # verification result" when the state mixes mock-derived and live-derived
    # facts. These four pin one referent and one predicate each.
    "cmd0_is_verified": {
        "type": "noul",
        "instructions": "Is `readme.install_commands[0].status` equal to 'verified'?",
    },
    "cmd1_is_broken": {
        "type": "noul",
        "instructions": "Is `readme.install_commands[1].status` equal to 'unpublished_404'?",
    },
    "all_python_checks_passed": {
        "type": "noul",
        "instructions": "Is `verification.python.failures` equal to 0?",
    },
    "llm_is_ok": {
        "type": "noul",
        "instructions": "Is `providers.llm.status` equal to 'ok'?",
    },
    # The same fact, asked as a Choice over an exhaustive set instead of a Noul.
    "llm_status_exhaustive": {
        "type": "choice",
        "instructions": "What is the current status of the generation provider?",
        "criteria": {
            "ok": "Requests are being accepted.",
            "quota_exhausted": "Requests are refused because a quota window is spent.",
            "misconfigured": "No usable key is configured.",
            "unreachable": "The provider cannot be contacted.",
        },
    },
}


def main() -> int:
    key = api_key()
    print("=" * 78)
    print("JEV QUESTIONNAIRE - primitives, formats, context, follow-ups")
    print("=" * 78)

    # ------------------------------------------------------------------ round 1
    print("\n--- ROUND 1: eleven questions, one request, mixed primitives ---")
    r1 = call(STATE, ROUND_1, key)
    answers = r1["answers"]
    for name, answer in answers.items():
        show(name, answer)
    print(f"\n  model={r1['model']}  usage={r1['usage']}  elapsed={r1['_elapsed']}s")

    print("\n  capability checks:")
    check("every question answered", len(answers) == len(ROUND_1),
          f"{len(answers)} answers for {len(ROUND_1)} questions")
    kinds = {a["type"] for a in answers.values()}
    check("all three primitives exercised", kinds == {"choice", "noul", "score"}, ",".join(sorted(kinds)))
    check("choice returns a full distribution",
          all("probabilities" in a and abs(sum(a["probabilities"].values()) - 1) < 0.02
              for a in answers.values() if a["type"] == "choice"))
    check("score returns a legend and level probabilities",
          all("legend" in a and "probabilities" in a
              for a in answers.values() if a["type"] == "score"))
    check("noul returns no confidence field",
          all("confidence" not in a for a in answers.values() if a["type"] == "noul"))
    check("every choice/score answer carries confidence",
          all("confidence" in a for a in answers.values() if a["type"] != "noul"))

    # Decision-ready behaviour on a fact with a known answer.
    engine = answers["engine_is_self_contained"]["noul"]
    check("checkable fact is decisive (|noul-1| < 0.25)", abs(engine - 1) < 0.25, f"noul={engine:.3f}")
    green = answers["ci_is_green"]["noul"]
    check("zero-failure fact reads as yes", green > 0.7, f"noul={green:.3f}")
    quota = answers["live_providers_unavailable"]["noul"]
    check("quota-exhausted fact reads as yes", quota > 0.7, f"noul={quota:.3f}")
    unprovable = answers["will_users_pay_for_it"]["noul"]
    check("unanswerable question is NOT confidently yes",
          unprovable < 0.8, f"noul={unprovable:.3f} (calibration)")

    # The hallucination-guard pair: both must agree.
    supported = answers["claim_supported"]["noul"]
    contradicted = answers["claim_contradicted"]["noul"]
    check("claim/contradiction pair agrees (support high, contradiction low)",
          supported > contradicted, f"supported={supported:.3f} vs contradicted={contradicted:.3f}")

    # Composed decision: both blockers true -> registry is the first move.
    r_blocker = answers["release_blocker"]
    both = answers["blocker_is_registry"]["noul"] > 0.5 and answers["blocker_is_quota"]["noul"] > 0.5
    check("composed decision is derivable in code", both,
          f"registry={answers['blocker_is_registry']['noul']:.2f} "
          f"quota={answers['blocker_is_quota']['noul']:.2f} "
          f"-> top option {r_blocker['choice']}")

    # ------------------------------------------------------------------ round 2
    print("\n\n--- ROUND 2: follow-up whose questions depend on a round-1 answer ---")
    print("  (the documented case: the first answer decides what to ask next)")
    chosen = r_blocker["choice"]
    follow = {
        "severity_of_chosen_blocker": {
            "type": "score",
            "instructions": (
                f"Given that `{chosen}` was selected as the top release blocker, "
                "how costly is it for a new user who tries the documented install today?"
            ),
            "criteria": [
                "A new user is not stopped: something still works for them.",
                "A new user is stopped and has no obvious workaround.",
                "A new user is stopped and the documentation actively misleads them.",
                "A new user is stopped, misled, and may conclude the project is broken.",
            ],
        },
        "wording_suggests_workaround": {
            "type": "noul",
            "instructions": (
                "Does `readme.install_commands` contain an entry with status 'verified' "
                "that a new user could follow instead of the failing one?"
            ),
        },
    }
    r2 = call(STATE, follow, key)
    for name, answer in r2["answers"].items():
        show(name, answer)
    print(f"  usage={r2['usage']}  elapsed={r2['_elapsed']}s")
    check("follow-up round answered both questions", len(r2["answers"]) == 2)
    check("follow-up saw a real prior answer as input",
          chosen in r_blocker["choice"], f"branch taken: {chosen}")
    check("workaround is detected in state",
          r2["answers"]["wording_suggests_workaround"]["noul"] > 0.5)

    # ------------------------------------------------------------------ round 3
    print("\n\n--- ROUND 3: the same judgment, vague then distilled ---")
    r3 = call(STATE, ROUND_3_VAGUE, key)
    for name, answer in r3["answers"].items():
        show(name, answer)
    print(f"  usage={r3['usage']}  elapsed={r3['_elapsed']}s")

    vague = [r3["answers"]["vague_readiness"]["noul"], r3["answers"]["vague_quality"]["noul"]]
    distilled = [r3["answers"]["distilled_install_works"]["noul"],
                 r3["answers"]["distilled_bounded_by_quota"]["noul"]]
    vagueness = sum(1 for v in vague if 0.25 < v < 0.75)
    decisiveness = sum(1 for v in distilled if v < 0.25 or v > 0.75)
    print(f"\n  vague questions landing in the undecidable 0.25-0.75 band: {vagueness}/2")
    print(f"  distilled questions landing outside it:                {decisiveness}/2")
    check("vague wording produces undecidable answers", vagueness >= 1,
          "  ".join(f"{v:.2f}" for v in vague))
    check("round-3 'distilled' questions were still ambiguous", decisiveness == 0,
          "  ".join(f"{v:.2f}" for v in distilled)
          + "  <- better vocabulary is not the same as a well-defined scope")

    # ------------------------------------------------------------------ round 4
    print("\n\n--- ROUND 4: the same facts with the scope actually pinned ---")
    r4 = call(STATE, ROUND_4_SCOPED, key)
    for name, answer in r4["answers"].items():
        show(name, answer)
    print(f"  usage={r4['usage']}  elapsed={r4['_elapsed']}s")

    scoped = [r4["answers"][k]["noul"] for k in
              ("cmd0_is_verified", "cmd1_is_broken", "all_python_checks_passed", "llm_is_ok")]
    outside = sum(1 for v in scoped if v < 0.25 or v > 0.75)
    print(f"\n  scoped questions outside the undecidable band: {outside}/4")
    print(f"  before (round 3), outside the band            : {decisiveness}/2")
    check("scoping the question makes the answer decisive", outside == 4,
          "  ".join(f"{v:.2f}" for v in scoped))
    check("a negative fact reads as a low noul",
          r4["answers"]["llm_is_ok"]["noul"] < 0.25,
          f"{r4['answers']['llm_is_ok']['noul']:.2f}")
    check("the same fact as an exhaustive Choice agrees with the Noul",
          r4["answers"]["llm_status_exhaustive"]["choice"] == "quota_exhausted",
          r4["answers"]["llm_status_exhaustive"]["choice"])

    print("\n" + "=" * 78)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name in FAILED:
        print(f"  - {name}")
    print("=" * 78)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
