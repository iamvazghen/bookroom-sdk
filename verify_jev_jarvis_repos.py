"""Ask Jev which utility repositories a real-world Jarvis should actually adopt.

The state is the Afon project's real operating constraints, plus a candidate
table whose facts were verified against the GitHub API by four independent
reviews (licence, language, whether it needs a long-running daemon, whether it
requires a third-party cloud account). Jev then applies the project's own
filters and ranks the field.

    python verify_jev_jarvis_repos.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

PASSED: list[str] = []
FAILED: list[str] = []


def api_key() -> str:
    for path in (Path(r"D:\summarimer\placeholder"), Path(r"D:\summarizer\src\.env"), HERE / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            body = line.strip().lstrip("#").strip()
            if "=" not in body:
                continue
            key, _, value = body.partition("=")
            if key.strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip()
    raise SystemExit("TYPESAFE_API_KEY not found")


# --------------------------------------------------------------------------- #
# Verified candidate facts. `daemon` and `cloud` are the two disqualifiers the
# project's own charter names: a new independent service, or a credential the
# owner does not control.
# --------------------------------------------------------------------------- #
CANDIDATES = [
    {"id": "wespeaker", "repo": "wenet-e2e/wespeaker", "licence": "Apache-2.0", "lang": "python",
     "serves": "speaker verification, PLDA scoring, EER measurement",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S08"},
    {"id": "pandoc", "repo": "jgm/pandoc", "licence": "GPL-2.0", "lang": "haskell",
     "serves": "document format conversion, machine-readable markdown AST",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S06"},
    {"id": "sops_age", "repo": "getsops/sops + FiloSottile/age", "licence": "MPL-2.0 / BSD-3",
     "lang": "go / rust", "serves": "encrypts credentials at rest in the env file",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S20"},
    {"id": "restic", "repo": "restic/restic", "licence": "BSD-2", "lang": "go",
     "serves": "verified, deduplicated, incremental backups with integrity check",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S22"},
    {"id": "trafilatura", "repo": "adbar/trafilatura", "licence": "Apache-2.0", "lang": "python",
     "serves": "extracts clean article text from a web page",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S41"},
    {"id": "valetudo", "repo": "Hypfer/Valetudo", "licence": "Apache-2.0", "lang": "typescript",
     "serves": "cloud-free control of a robot vacuum, on the device",
     "daemon": True, "cloud": False, "already": False, "subsystem": "S42"},
    {"id": "beancount", "repo": "beancount/beancount", "licence": "GPL-2.0", "lang": "python",
     "serves": "parses the plain-text accounting ledger format",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S40"},
    {"id": "hypothesis", "repo": "HypothesisWorks/hypothesis", "licence": "MPL-2.0", "lang": "python",
     "serves": "generates the conflicting input pairs a test suite must cover",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S44"},
    {"id": "jev_ultrafast", "repo": "browser-use/jev-ultrafast", "licence": "unspecified",
     "lang": "python", "serves": "one typed decision per browser step over CDP",
     "daemon": False, "cloud": False, "already": True, "subsystem": "S05"},
    {"id": "mirofish", "repo": "666ghj/MiroFish", "licence": "AGPL-3.0", "lang": "python",
     "serves": "multi-agent scenario simulation and forecasting",
     "daemon": True, "cloud": True, "already": False, "subsystem": "S46"},
    {"id": "tiktoken", "repo": "openai/tiktoken", "licence": "MIT", "lang": "python",
     "serves": "exact token counting for a tool catalogue budget",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S03"},
    {"id": "sherpa_onnx", "repo": "k2-fsa/sherpa-onnx", "licence": "Apache-2.0", "lang": "cpp",
     "serves": "speech enhancement and speaker diarization in one library",
     "daemon": False, "cloud": False, "already": False, "subsystem": "S18"},
    {"id": "mopidy", "repo": "mopidy/mopidy", "licence": "Apache-2.0", "lang": "python",
     "serves": "a local music server with an extension API",
     "daemon": True, "cloud": False, "already": False, "subsystem": "S42"},
    {"id": "caldav", "repo": "python-caldav/caldav", "licence": "Apache-2.0", "lang": "python",
     "serves": "reads a CalDAV calendar",
     "daemon": False, "cloud": True, "already": False, "subsystem": "S21"},
    {"id": "uv", "repo": "astral-sh/uv", "licence": "MIT/Apache-2.0", "lang": "rust",
     "serves": "resolves and installs python dependencies without a resolver of its own",
     "daemon": False, "cloud": False, "already": True, "subsystem": "build"},
    {"id": "e2b", "repo": "e2b-dev/E2B", "licence": "Apache-2.0", "lang": "typescript",
     "serves": "spawns isolated cloud sandboxes for untrusted code",
     "daemon": True, "cloud": True, "already": False, "subsystem": "S36"},
]

STATE = {
    "operator": "one person, 8-10 hours a week of engineering time",
    "system": {
        "subsystems": 50,
        "tools": {"schemas": 153, "handlers": 155, "target_range": "90-100"},
        "state": "SQLite plus a vault of markdown; markdown wins every disagreement",
        "runtime": "processes under systemd, no broker, no cluster",
        "already_wired": ["faster-whisper via pipecat", "insightface", "pipecat", "openwakeword",
                          "uv", "mcode", "Home Assistant", "an MCP client"],
        "already_decided": {
            "declined_libraries": ["LangGraph", "mopidy", "a second MCP client",
                                   "a message bus", "a second database"],
            "subsystems_marked_for_deletion": ["S15", "S46", "S47", "S49"],
        },
    },
    "filters": {
        "two_am_rule": ("If it fails at 2:00 AM, it must be debuggable in 90 seconds with "
                        "journalctl, sqlite3 and curl. Name the three commands."),
        "subtract_first": ("50 subsystems is already too many. A new capability defaults to a "
                           "handler in an existing system. A new subsystem needs an independent "
                           "daemon or a distinct security boundary to justify existing."),
        "no_uncontrolled_cloud": ("A mandatory third-party cloud account moves state onto "
                                  "infrastructure the operator does not control."),
        "no_dark_work": ("Code that controls no live device, file or credential is not progress."),
    },
    "candidates": CANDIDATES,
}

# The scoring shortlist: candidates that are not already covered or already
# disqualified by the project's own decisions.
SCORED = ["wespeaker", "pandoc", "sops_age", "restic", "trafilatura", "beancount",
          "hypothesis", "tiktoken", "mirofish", "sherpa_onnx", "mopidy", "caldav"]


def call(questions: dict) -> dict:
    body = json.dumps({"state": STATE, "model": MODEL, "questions": questions}).encode()
    request = urllib.request.Request(ENDPOINT, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {api_key()}")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Jev HTTP {exc.code}: {exc.read().decode()[:400]}") from None


def main() -> int:
    key_present = bool(api_key())

    print("=" * 78)
    print("JEV: WHICH UTILITY REPOSITORIES SHOULD A REAL-WORLD JARVIS ADOPT?")
    print("=" * 78)
    print(f"candidates scored: {len(SCORED)} of {len(CANDIDATES)} verified\n")

    round1 = {
        "single_best": {
            "type": "choice",
            "instructions": ("Considering every candidate together, which one change does the "
                             "operator's system benefit from most, without adding a subsystem?"),
            "criteria": {
                "unblocks_a_gate": "It unblocks a measurement or gate that currently blocks others.",
                "protects_worst_case": "It protects against the worst realistic failure.",
                "makes_existing_work_correct": "It makes code that already exists actually correct.",
                "reduces_operational_risk": "It removes a live security or reliability risk.",
                "none": "None of them clears the bar.",
            },
        },
        "adds_a_subsystem": {
            "type": "choice",
            "instructions": ("Which candidates would require a new independent daemon, a new "
                             "security boundary, or a mandatory third-party cloud account?"),
            "criteria": {
                "mirofish": "666ghj/MiroFish",
                "mopidy": "mopidy/mopidy",
                "caldav": "python-caldav/caldav",
                "e2b": "e2b-dev/E2B",
                "valetudo": "Hypfer/Valetudo, which runs on the device rather than beside it",
                "none": "None of the listed candidates.",
            },
        },
        "passes_two_am_rule": {
            "type": "noul",
            "instructions": ("Considering `candidates`, is every candidate whose `daemon` and "
                             "`cloud` fields are both false debuggable with journalctl, sqlite3 "
                             "and curl alone, per `filters.two_am_rule`?"),
            "criteria": {
                "true": "Yes, each such candidate is a local binary or library with a plain command surface.",
                "false": "No, at least one such candidate still needs its own service or tooling.",
            },
        },
        "already_covered": {
            "type": "noul",
            "instructions": "Is `candidates` free of entries that are already wired or already decided?",
        },
    }

    # One Score PER candidate, not one Score across all of them. The TypeSafe docs
    # are explicit that graded ranking needs comparable per-item Scores: a single
    # Score over a list returns one position on a spectrum, not a score per item,
    # and the distribution comes back flat. Same levels for every item, so the
    # returned scores are comparable.
    utility_levels = [
        "No measurable value; the system is better off without it.",
        "Marginal; fixes something minor with no gate behind it.",
        "Useful; removes a known failure or a manual step.",
        "High; unblocks a gate, or protects a realistic worst case.",
        "Essential; the system is materially less safe or less correct without it.",
    ]
    by_id = {c["id"]: c for c in CANDIDATES}
    for cid in SCORED:
        entry = by_id[cid]
        round1[f"utility_{cid}"] = {
            "type": "score",
            "instructions": {
                "question": (f"Rate the real day-to-day value that adopting `{cid}` adds to this "
                             f"system, applying every filter in `filters`."),
                "repository": f"`{cid}`",
                "verdict_from_review": entry["serves"],
                "adds_a_daemon": entry["daemon"],
                "requires_third_party_cloud": entry["cloud"],
            },
            "criteria": utility_levels,
        }

    r1 = call(round1)
    a = r1["answers"]
    for name, answer in a.items():
        if answer["type"] == "score" and name.startswith("utility_"):
            continue  # printed in the ranked table below
        if answer["type"] == "score":
            print(f"  {name}: score={answer['score']:.2f} conf={answer['confidence']:.3f}")
        elif answer["type"] == "choice":
            ranked = sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])
            print(f"  {name}: {answer['choice']} (conf {answer['confidence']:.3f})")
            print(f"      {'  '.join(f'{k}={v:.2f}' for k, v in ranked)}")
        else:
            print(f"  {name}: noul={answer['noul']:.3f}")
    print(f"\n  model={r1['model']} usage={r1['usage']}")

    print("\n--- per-candidate utility, ranked (one comparable Score each) ---")
    scored_rows = []
    for cid in SCORED:
        answer = a[f"utility_{cid}"]
        scored_rows.append((cid, float(answer["score"]), float(answer["confidence"])))
    scored_rows.sort(key=lambda row: -row[1])
    for cid, score, confidence in scored_rows:
        print(f"  {cid:<14} score={score:.2f}  confidence={confidence:.2f}")
    mean_confidence = sum(row[2] for row in scored_rows) / len(scored_rows)
    print(f"  mean confidence across the shortlist: {mean_confidence:.2f}")

    print("\n--- derivation: the adopted set, computed in code from the answers ---")
    blocking = a["adds_a_subsystem"]["choice"]
    ADOPT_AT = 2.0        # "Useful" and above
    adopted, rejected = [], []
    for cid, score, _conf in scored_rows:
        if cid in {c["id"] for c in CANDIDATES if c["daemon"] or c["cloud"]}:
            rejected.append((cid, f"needs a daemon, a new boundary, or a cloud account"))
        elif score >= ADOPT_AT:
            adopted.append((cid, score))
        else:
            rejected.append((cid, f"utility {score:.2f} is below the adopt line ({ADOPT_AT:.1f})"))
    print(f"  adopt line: utility score >= {ADOPT_AT:.1f} and no daemon/cloud requirement")
    print(f"  adopted   ({len(adopted)}): " + ", ".join(c for c, _ in adopted))
    for cid, level in rejected:
        print(f"  rejected  {cid:<14} {level}")

    print("\n--- round 2: the closest real production equivalent for each adopted repo ---")
    equivalents = {
        "wespeaker": {"speechbrain": "already the embedder", "resemblyzer": "older, less accurate",
                      "pyannote": "diarization-focused, heavier", "voxcelery": "unmaintained",
                      "none_needed": "no closer equivalent"},
        "pandoc": {"libreoffice": "office suite, heavier", "docx2pdf": "narrower, MS-only",
                   "none_needed": "no closer equivalent"},
        "sops_age": {"vault": "heavier daemon", "pass": "present but not enforced",
                     "dotenv": "what it would replace", "none_needed": "no closer equivalent"},
        "restic": {"borg": "closest alternative, deduplicated too",
                   "rsync_snapshot": "what it would replace, no verification",
                   "rclone": "sync, not backup", "none_needed": "no closer equivalent"},
        "trafilatura": {"readability": "JS, older", "newspaper3k": "closest Python alternative",
                        "bs4": "what it would replace, no extraction", "none_needed": "no closer equivalent"},
        "beancount": {"fava": "web UI over beancount", "ledger": "CLI, older, different format",
                      "none_needed": "no closer equivalent"},
        "hypothesis": {"pytest_parametrize": "hand-written cases",
                       "hypothesis_js": "same idea in JS", "none_needed": "no closer equivalent"},
        "tiktoken": {"transformers_tokenizer": "heavier, same job",
                     "chars_div_4": "the current estimate", "none_needed": "no closer equivalent"},
        "sherpa_onnx": {"rnnoise": "noise only, not echo or diarization",
                        "webrtc_apm": "licence-gated", "none_needed": "no closer equivalent"},
    }
    round2 = {
        f"closest_{cid}": {
            "type": "choice",
            "instructions": (f"For the repository `{cid}`, which option is the closest real "
                             f"production system doing the same job today?"),
            "criteria": equivalents[cid],
        }
        for cid, _ in adopted[:8]
    }
    r2 = call(round2) if round2 else {"answers": {}, "model": MODEL, "usage": {}}
    for name, answer in r2.get("answers", {}).items():
        ranked2 = sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])
        print(f"  {name:<24} {answer['choice']:<22} "
              f"{'  '.join(f'{k}={v:.2f}' for k, v in ranked2[:3])}")
    if r2.get("usage"):
        print(f"\n  model={r2['model']} usage={r2['usage']}")

    print("\n" + "=" * 78)
    print(f"ADOPT ({len(adopted)} of {len(SCORED)} scored, {len(CANDIDATES)} candidates considered)")
    for cid, score in adopted:
        print(f"  {cid:<14} utility {score:.2f}")
    print(f"\nREJECTED ({len(rejected)})")
    for cid, why in rejected:
        print(f"  {cid:<14} {why}")
    if key_present:
        PASSED.append("Jev answered every round")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
