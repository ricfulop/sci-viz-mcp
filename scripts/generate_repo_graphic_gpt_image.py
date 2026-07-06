#!/usr/bin/env python3
"""Generate the Sci-Viz MCP repo hero image with GPT Image.

Requires:
    export OPENAI_API_KEY=...

Default output:
    assets/sci-viz-mcp-hero.png
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT = ROOT / "assets" / "sci-viz-mcp-hero.prompt.md"
DEFAULT_OUTPUT = ROOT / "assets" / "sci-viz-mcp-hero.png"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_default_env_files(explicit: Path | None = None) -> None:
    if explicit is not None:
        load_env_file(explicit)
        return
    for base in [Path.cwd(), ROOT, *ROOT.parents]:
        load_env_file(base / ".env")


def load_prompt(path: Path) -> str:
    text = path.read_text()
    if text.lstrip().startswith("#"):
        # Keep markdown prose; GPT Image handles this well.
        return text
    return text.strip()


def generate(prompt: str, output: Path, model: str, size: str) -> Path:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Export it and rerun, e.g.\n"
            "  export OPENAI_API_KEY=sk-...\n"
            f"  python3 {Path(__file__).relative_to(ROOT)}"
        )

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": "high",
        "n": 1,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        body = re.sub(r"sk-[A-Za-z0-9_*.-]+", "sk-[REDACTED]", body)
        raise SystemExit(f"OpenAI image generation failed ({e.code}):\n{body}") from e

    try:
        b64 = data["data"][0]["b64_json"]
    except (KeyError, IndexError) as e:
        raise SystemExit(f"Unexpected OpenAI response:\n{json.dumps(data, indent=2)[:4000]}") from e

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(b64))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="gpt-image-1")
    parser.add_argument("--size", default="1536x1024")
    parser.add_argument("--env-file", type=Path,
                        help="Optional .env file containing OPENAI_API_KEY")
    args = parser.parse_args()

    load_default_env_files(args.env_file)
    out = generate(load_prompt(args.prompt), args.output, args.model, args.size)
    print(out)


if __name__ == "__main__":
    main()
