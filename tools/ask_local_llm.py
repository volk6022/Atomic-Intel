"""Bridge to local LM Studio for sub-agent codebase analysis.

Usage:
    python tools/ask_local_llm.py --prompt "Опиши модель" src/foo.py src/bar.py
    python tools/ask_local_llm.py --prompt-file p.txt src/foo.py
    echo "prompt" | python tools/ask_local_llm.py --stdin-prompt src/foo.py

Hard-coded for the project's local LM Studio endpoint.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ENDPOINT = "http://172.30.80.1:20022/v1/chat/completions"
MODEL = "qwen3.5-9b-claude-4.6-opus-reasoning-distilled"
DEFAULT_SYSTEM = (
    "Ты помогаешь анализировать код Python-проекта. "
    "Отвечай кратко, по делу, на русском. "
    "Не цитируй большие куски кода — давай выводы и сигнатуры."
)
THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def build_payload(files: list[Path], max_chars: int) -> str:
    parts: list[tuple[Path, str]] = []
    total = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"warning: cannot read {p}: {e}", file=sys.stderr)
            continue
        parts.append((p, text))
        total += len(text)

    if total > max_chars and parts:
        ratio = max_chars / total
        truncated_names = []
        new_parts: list[tuple[Path, str]] = []
        for p, text in parts:
            keep = max(500, int(len(text) * ratio))
            if keep < len(text):
                truncated_names.append(f"{p} ({len(text)}→{keep})")
                text = text[:keep] + f"\n# ...TRUNCATED ({len(text)-keep} chars)...\n"
            new_parts.append((p, text))
        parts = new_parts
        print(
            f"warning: total {total} chars > max {max_chars}, truncated: "
            + ", ".join(truncated_names),
            file=sys.stderr,
        )

    chunks = []
    for p, text in parts:
        try:
            rel = p.relative_to(Path.cwd())
        except ValueError:
            rel = p
        chunks.append(f"### FILE: {rel.as_posix()}\n```\n{text}\n```\n")
    return "\n".join(chunks)


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.stdin_prompt:
        return sys.stdin.read()
    raise SystemExit("error: provide --prompt, --prompt-file, or --stdin-prompt")


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--prompt-file")
    ap.add_argument("--stdin-prompt", action="store_true")
    ap.add_argument("--system", default=DEFAULT_SYSTEM)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--max-chars", type=int, default=400_000)
    ap.add_argument("--no-strip-think", action="store_true")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("files", nargs="*", type=Path)
    args = ap.parse_args()

    prompt = resolve_prompt(args)
    files_block = build_payload(args.files, args.max_chars) if args.files else ""

    user_content = prompt
    if files_block:
        user_content = f"{prompt}\n\n---\n{files_block}"

    messages = [
        {"role": "system", "content": args.system},
        {"role": "user", "content": user_content},
    ]

    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }

    try:
        with httpx.Client(timeout=args.timeout) as client:
            r = client.post(ENDPOINT, json=body)
    except httpx.HTTPError as e:
        print(f"error: HTTP request failed: {e}", file=sys.stderr)
        return 1

    if r.status_code != 200:
        print(f"error: HTTP {r.status_code}", file=sys.stderr)
        print(r.text[:4000], file=sys.stderr)
        return 1

    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("error: unexpected response shape", file=sys.stderr)
        print(str(data)[:4000], file=sys.stderr)
        return 1

    if not args.no_strip_think:
        content = strip_think(content)

    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
