"""ControlPlane's read-only validation MCP; only configured repository targets."""
from pathlib import Path
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from worker import validate

Target = Literal['brb', 'cdt']
Family = Literal['jira-as-code', 'github-as-code', 'governance-as-code', 'llm-as-code']
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)


def create_server(targets=None):
    targets = targets or {'brb': Path('/inputs/brb'), 'cdt': Path('/inputs/cdt')}
    server = MCPServer('validation_mcp', instructions=(
        'Read-only static validation of canonical pascode YAML and declared schemas. '
        'Missing schemas are coverage gaps and fail validation. '
        'Success does not establish live permissions, deployment or exhaustive schema coverage. '
        'Only brb/cdt targets are exposed; no arbitrary paths, writes or provisioning.'
    ))

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def validation_list_targets() -> dict[str, Any]:
        """List mounted validation targets and available pascode families. Read-only."""
        return {'targets': [{'target': name, 'available': root.is_dir(),
                             'families': sorted(p.name for p in root.glob('*-as-code') if p.is_dir())}
                            for name, root in targets.items()]}

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def validation_validate_pascode(
        target: Target,
        family: Family | None = None,
        schema_target: Target | None = None,
        include_valid: bool = False,
    ) -> dict[str, Any]:
        """Validate YAML/schema and Jira references for brb or cdt; missing schemas fail.

        Select one family or all present families. schema_target defaults to target;
        explicitly select another target to check against its schema contract.
        By default results include only failed checks; counts include every file.
        No live probes, credential access, remote schema retrieval or mutation.
        """
        if target not in targets or (schema_target is not None and schema_target not in targets):
            return {'error': 'unknown_target'}
        report = validate(targets[target], targets[schema_target or target], family)
        report['target'] = target
        report['schema_target'] = schema_target or target
        selected = [record for record in report['results'] if include_valid or record['errors']]
        report['results'] = selected[:100]
        report['truncated'] = len(selected) > 100
        report['result_count'] = len(selected)
        return report

    return server


if __name__ == '__main__':
    create_server().run(transport='stdio')
