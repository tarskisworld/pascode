#!/usr/bin/env python3
"""
Prompt-first test suite generator.

This tool does not attempt to infer semantic correctness itself.
It prepares structured prompts that an LLM can use to generate
high-quality tests for any YAML set.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def list_yaml_context(input_dir: Path) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for path in sorted(input_dir.rglob("*.yaml")):
        rel = path.relative_to(input_dir)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            root_type = type(data).__name__
            top_keys = sorted(list(data.keys())) if isinstance(data, dict) else []
            context.append(
                {
                    "file": str(rel),
                    "root_type": root_type,
                    "top_level_keys": top_keys,
                }
            )
        except Exception as exc:  # noqa: BLE001
            context.append(
                {
                    "file": str(rel),
                    "root_type": "parse_error",
                    "top_level_keys": [],
                    "parse_error": str(exc),
                }
            )
    return context


def build_prompt_bundle(input_dir: Path, yaml_context: list[dict[str, Any]]) -> dict[str, Any]:
    files = [c["file"] for c in yaml_context]
    system_prompt = (
        "Given YAML configuration files that represent desired state, generate a deterministic "
        "conformance test suite that verifies whether the current/live state matches the YAML state. "
        "Include: static validation, reference consistency checks, read-only API/state comparison tests, "
        "optional sandbox mutation tests, severity (P0/P1/P2), expected outcomes, and remediation hints."
    )

    user_prompt = f"""
Repository YAML directory: {input_dir}

Discovered YAML files:
{json.dumps(yaml_context, indent=2)}

Task:
1. Produce a complete test plan for these YAML files as desired-state specifications.
2. Include test IDs, prerequisites, execution steps, expected results, and failure interpretation.
3. Separate tests into:
   - static/no-network
   - read-only runtime/API state-conformance checks
   - optional sandbox mutation
4. Add dependency ordering so tests run in a safe sequence.
5. Output both:
   - human-readable markdown plan
   - machine-readable JSON test catalog
6. For each runtime test, explicitly state:
   - desired value/behavior from YAML
   - observed value/behavior from live system
   - pass/fail drift decision
7. Avoid assumptions that are not grounded in file names/keys above.
"""

    schema_hint = {
        "tests": [
            {
                "id": "T-001",
                "severity": "P0|P1|P2",
                "category": "static|read_only|mutation",
                "purpose": "string",
                "targets": ["file-or-endpoint"],
                "prerequisites": ["string"],
                "steps": ["string"],
                "expected": ["string"],
                "failure_interpretation": ["string"],
                "remediation": ["string"],
            }
        ],
        "execution_order": ["T-001", "T-002"],
    }

    return {
        "meta": {
            "mode": "prompt_first",
            "input_dir": str(input_dir),
            "yaml_file_count": len(files),
            "files": files,
        },
        "prompts": {
            "system": system_prompt,
            "user": user_prompt.strip(),
            "output_schema_hint": schema_hint,
        },
    }


def write_markdown(bundle: dict[str, Any], out_path: Path):
    lines = [
        "# Prompt-Based YAML Test Suite",
        "",
        "## Mode",
        "- Prompt-first generation (LLM-driven test synthesis)",
        "",
        "## Inputs",
        f"- Directory: `{bundle['meta']['input_dir']}`",
        f"- YAML files: `{bundle['meta']['yaml_file_count']}`",
        "",
        "## Files",
    ]
    for f in bundle["meta"]["files"]:
        lines.append(f"- `{f}`")
    lines.extend(
        [
            "",
            "## Use",
            "1. Provide `prompts.system` as system instructions.",
            "2. Provide `prompts.user` as task payload.",
            "3. Ask model to return JSON matching `prompts.output_schema_hint` and a markdown test plan.",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=".")
    parser.add_argument("--output-dir", default="analysis/prompts/generated")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ctx = list_yaml_context(input_dir)
    bundle = build_prompt_bundle(input_dir, ctx)

    bundle_path = output_dir / "prompt_test_bundle.json"
    plan_path = output_dir / "PROMPT-TEST-PLAN.md"
    system_path = output_dir / "PROMPT-SYSTEM.txt"
    user_path = output_dir / "PROMPT-USER.txt"

    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    write_markdown(bundle, plan_path)
    system_path.write_text(bundle["prompts"]["system"] + "\n", encoding="utf-8")
    user_path.write_text(bundle["prompts"]["user"] + "\n", encoding="utf-8")

    print(f"wrote: {bundle_path}")
    print(f"wrote: {plan_path}")
    print(f"wrote: {system_path}")
    print(f"wrote: {user_path}")


if __name__ == "__main__":
    main()
