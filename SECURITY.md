# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 2.x | yes |
| < 2.0 | no |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub's security advisory form for this
repository: **Security → Report a vulnerability**. If that is unavailable,
open an issue that says only "security report available on request" with no
technical detail, and a maintainer will arrange a private channel.

Include, as far as you can:

- what an attacker can do, and what they need in order to do it
- the version or commit you tested
- reproduction steps, logs, or a proof of concept
- whether any real key or book content was exposed

You can expect an acknowledgement within 72 hours and a substantive reply
within seven days. Please give us a reasonable window to ship a fix before
disclosing publicly.

## Threat model

Bookroom handles two classes of sensitive input: **provider credentials** and
**copyrighted book content**. Both are treated as sensitive here.

### What this project does to protect your keys

- The Python SDK reads `GEMINI_API_KEY` and `TYPESAFE_API_KEY` from the
  environment. They are never written into an artifact, a log, a manifest, or
  an error message. `run_baseline.py` contains a redaction pass for this
  reason, because the engine's tracebacks are otherwise echoed verbatim.
- The TypeScript, React and Next.js clients **never receive those keys**. They
  talk to the Python facade over HTTP and authenticate with a separate,
  non-provider **facade token**. The React hook
  `useBookroomClient` deliberately throws if you pass a token in a browser.
- `.env` is git-ignored; `.env.example` contains no secrets. A secret scan runs
  over every staged file before a commit in this repository.

### Known exposure to be aware of

- The facade serves generated artifacts over `GET /v1/download`. It is confined
  to the directory holding the named report, and rejects any name that escapes
  it. **The facade itself has no user authentication** beyond the token, so
  bind it to loopback and put it behind a reverse proxy with TLS and real
  authorization before exposing it to any network you do not control.
- Anyone holding the facade token can read every generated report on that
  server. Treat the token as a credential and scope it accordingly.
- `http://` is used by default. Use `https://` outside localhost.
- The engine sends book excerpts to the configured LLM and review providers.
  If the book is confidential, point `BOOKROOM_LLM_BASE_URL` and
  `BOOKROOM_JEV_BASE_URL` at an endpoint you control.

### We never ask for your keys

No issue, discussion, or support request will ask you to paste an API key. If
something does, it is not us — and you should rotate the key.

## Third-party dependencies

The engine depends on `httpx`, `pymupdf`, `reportlab`, `Markdown`,
`beautifulsoup4`, `ebooklib` and `python-dotenv`; the TypeScript client has no
runtime dependencies. Report a vulnerable dependency through the same private
channel.
