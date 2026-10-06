import json
import urllib.error
import urllib.request

for name in ("bookroom-sdk", "summarizer-sdk", "bookroom"):
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.load(response)
        print(f"PyPI {name:<16} TAKEN  latest={data['info']['version']}")
    except urllib.error.HTTPError as exc:
        print(f"PyPI {name:<16} available ({exc.code})")
    except Exception as exc:  # noqa: BLE001
        print(f"PyPI {name:<16} check failed: {type(exc).__name__}")

# Are the third-party publishing frontends installed?
import importlib.util

for tool, module in (("twine", "twine"), ("build", "build"), ("uv", None)):
    if module is None:
        continue
    print(f"{tool:<16} {'installed' if importlib.util.find_spec(module) else 'not installed'}")
