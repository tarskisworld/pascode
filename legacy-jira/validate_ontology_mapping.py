#!/usr/bin/env python3
import sys
from pathlib import Path
import yaml

import os
BASE = Path(os.environ['PASCODE_JIRA_ROOT']).resolve()
import json as _context_json
_context_file = os.environ.get('PASCODE_LEGACY_CONTEXT')
CONTEXT = _context_json.loads(Path(_context_file).read_text()) if _context_file else {}
CONFIG = BASE / 'config'
MAPPING = BASE / 'mapped' / 'ontology-mapping.yaml'

required_files = [
    CONFIG / 'projects.yaml',
    CONFIG / 'permission-schemes.yaml',
    CONFIG / 'workflow-definitions.yaml',
    CONFIG / 'board-filters.yaml',
    CONFIG / 'automation-triggers.yaml',
    CONFIG / 'service-account-registry.yaml',
]


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def main():
    errors = []

    if not MAPPING.exists():
        print(f'ERROR: mapping file missing: {MAPPING}')
        return 1

    mapping = load_yaml(MAPPING)
    mappings = mapping.get('mappings', {})

    for f in required_files:
        if not f.exists():
            errors.append(f'missing source file: {f.name}')
            continue

        key = f.name if f.name in mappings else f'config/{f.name}' if f'config/{f.name}' in mappings else None
        if key is None:
            errors.append(f'missing mapping entry for: {f.name}')
            continue

        root = mappings[key].get('root')
        if not root:
            errors.append(f'mapping root missing for: {f.name}')
            continue

        doc = load_yaml(f)
        if root not in doc:
            errors.append(f'{f.name}: root key {root} not found')

    # rule check: membership must be present when role bindings exist
    sa = load_yaml(CONFIG / 'service-account-registry.yaml').get('service_account_registry', {})
    for name, cfg in sa.items():
        has_bindings = bool(cfg.get('project_role_bindings'))
        requires_membership = bool(cfg.get('project_membership_required'))
        if has_bindings and not requires_membership:
            errors.append(f'{name}: project_role_bindings present but project_membership_required is not true')

    if errors:
        print('FAILED')
        for e in errors:
            print(f'- {e}')
        return 1

    print('OK: ontology mapping coverage and baseline consistency checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
