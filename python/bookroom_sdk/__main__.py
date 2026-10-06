"""Command line entry point: ``python -m bookroom_sdk``.

    python -m bookroom_sdk serve   --port 8787
    python -m bookroom_sdk check
    python -m bookroom_sdk describe
    python -m bookroom_sdk guide   book.epub --output-dir ./out
    python -m bookroom_sdk extract book.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import Bookroom, __version__


def _client(args: argparse.Namespace) -> Bookroom:
    return Bookroom.from_env(
        **{key: value for key, value in {
            "app_root": args.app_root,
            "output_dir": args.output_dir,
        }.items() if value is not None}
    )


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    room = _client(args)
    serve(room, host=args.host, port=args.port,
          token=args.token or (__import__("os").environ.get("BOOKROOM_FACADE_TOKEN") or None))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    report = _client(args).check()
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def _cmd_describe(args: argparse.Namespace) -> int:
    print(json.dumps(_client(args).describe(), indent=2, ensure_ascii=False))
    return 0


def _cmd_guide(args: argparse.Namespace) -> int:
    room = _client(args)
    result = room.summarize.study_guide(
        args.source,
        options={"language": args.language, "digest_length": args.length},
        output_slug=args.slug,
        review=not args.no_review,
        progress=lambda message, **kw: print(f"  {message}", file=sys.stderr),
    )
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False, default=str))
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    room = _client(args)
    document = room.extract.extract(args.source, include_text=args.text)
    payload = document.as_dict(include_text=args.text)
    if args.text:
        for section in payload["sections"]:
            section["text"] = section["text"][:400] + ("..." if len(section["text"]) > 400 else "")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookroom_sdk",
        description="Book Summarizer SDK - use every Bookroom capability from your own code.",
    )
    parser.add_argument("--version", action="version", version=f"bookroom-sdk {__version__}")
    parser.add_argument("--app-root", help="Directory containing book_pipeline.py")
    parser.add_argument("--output-dir", help="Where generated reports are written")

    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve", help="Run the HTTP facade for other-language SDKs")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8787)
    serve_parser.add_argument("--token", help="Require this bearer token on every request")
    serve_parser.set_defaults(func=_cmd_serve)

    sub.add_parser("check", help="Verify LLM and JEv credentials").set_defaults(func=_cmd_check)
    sub.add_parser("describe", help="Print the active configuration and capabilities").set_defaults(
        func=_cmd_describe)

    guide_parser = sub.add_parser("guide", help="Generate a complete study guide")
    guide_parser.add_argument("source")
    guide_parser.add_argument("--slug", help="Output folder name")
    guide_parser.add_argument("--language", default="English")
    guide_parser.add_argument("--length", default="standard", choices=("brief", "standard", "deep"))
    guide_parser.add_argument("--no-review", action="store_true", help="Skip JEv review")
    guide_parser.set_defaults(func=_cmd_guide)

    extract_parser = sub.add_parser("extract", help="Extract sections from an EPUB or PDF")
    extract_parser.add_argument("source")
    extract_parser.add_argument("--text", action="store_true", help="Include a text preview")
    extract_parser.set_defaults(func=_cmd_extract)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
