#!/usr/bin/env python3
"""
Prompt-first companion runner.

Consumes `prompt_test_bundle.json` and emits:
- an operator checklist
- a copy/paste prompt packet

No heuristic static assertions are executed here by design.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle",
        default="analysis/prompts/generated/prompt_test_bundle.json",
        help="Path to prompt bundle JSON produced by generate_test_suite_from_yaml.py",
    )
    parser.add_argument(
        "--out-dir",
        default="analysis/prompts/generated",
        help="Directory to write prompt execution artifacts",
    )
    args = parser.parse_args()

    bundle_path = Path(args.bundle).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    checklist_path = out_dir / "PROMPT-EXECUTION-CHECKLIST.md"
    packet_path = out_dir / "PROMPT-PACKET.md"

    checklist = [
        "# Prompt Execution Checklist",
        "",
        "## Steps",
        "1. Send `PROMPT-SYSTEM.txt` as system prompt.",
        "2. Send `PROMPT-USER.txt` as user prompt.",
        "3. Request two outputs:",
        "- machine-readable JSON test catalog",
        "- markdown test plan",
        "4. Validate returned JSON against `output_schema_hint` in `prompt_test_bundle.json`.",
        "5. Save model outputs into `analysis/prompts/generated/` for traceability.",
        "",
        "## Input Summary",
        f"- Input dir: `{bundle['meta']['input_dir']}`",
        f"- YAML files: `{bundle['meta']['yaml_file_count']}`",
    ]
    checklist_path.write_text("\n".join(checklist) + "\n", encoding="utf-8")

    packet = [
        "# Prompt Packet",
        "",
        "## System Prompt",
        "```text",
        bundle["prompts"]["system"],
        "```",
        "",
        "## User Prompt",
        "```text",
        bundle["prompts"]["user"],
        "```",
        "",
        "## Output Schema Hint",
        "```json",
        json.dumps(bundle["prompts"]["output_schema_hint"], indent=2),
        "```",
    ]
    packet_path.write_text("\n".join(packet) + "\n", encoding="utf-8")

    print(f"bundle: {bundle_path}")
    print(f"wrote: {checklist_path}")
    print(f"wrote: {packet_path}")


if __name__ == "__main__":
    main()

