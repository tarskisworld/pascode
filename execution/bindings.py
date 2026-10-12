"""Prepare credential-free site bindings; identifiers require naming registration."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from runner import validate


DESCRIPTIONS = {
    'Bug': 'A defect that needs correction.',
    'Spike': 'A bounded investigation to resolve a design or implementation question.',
    'Decision': 'An architectural decision and its rationale.',
    'Proposal': 'A proposed system change for investigation and review.',
    'Risk': 'A system risk and its treatment.',
    'Security Finding': 'A security finding requiring assessment and remediation.',
    'Problem': 'An underlying cause requiring investigation and remediation.',
    'Change': 'An operational change through assessment, implementation and verification.',
}


def generate(docs):
    namespace = urlparse(docs['site']['site']['base_url']).hostname.split('.')[0]
    projects = docs['projects']['projects']
    types = {n for p in projects for n in p['work_types']}
    schemes = docs['workflow-definitions']['workflow_schemes']
    defaults = {}
    for scheme in schemes:
        project = next(p for p in projects if p['work_type_scheme'] == scheme)
        preferred = 'Service Request' if project['project_type'] == 'service_desk' else 'Task'
        defaults[scheme] = preferred if preferred in project['work_types'] else next(n for n in project['work_types'] if n != 'Subtask')
    return {
        'deployment': {
            'project_keys': [p['key'] for p in projects],
            'work_type_metadata': {n: {'description': DESCRIPTIONS[n], 'is_subtask': False}
                                   for n in sorted(types & DESCRIPTIONS.keys())},
        },
        'workflows': {n: {'name': f'{namespace}-{n}-workflow'} for n in docs['workflow-definitions']['workflow_definitions']},
        'work_type_schemes': {n: {'name': f'{namespace}-{n}-work-type-scheme', 'default_work_type': defaults[n]} for n in schemes},
        'workflow_schemes': {n: {'name': f'{namespace}-{n}-workflow-scheme'} for n in schemes},
        'permission_schemes': {n: {'name': f'{namespace}-{n}-permission-scheme'} for n in docs['permission-profiles']['permission_profiles']},
        'project_roles': {n: {'name': f'{namespace}-jira-{n}'} for n in docs['permission-profiles']['project_roles']},
    }


def identifiers(bindings):
    kinds = {'workflows': 'jira-workflow', 'work_type_schemes': 'jira-issue-type-scheme',
             'workflow_schemes': 'jira-workflow-scheme', 'permission_schemes': 'jira-permission-scheme',
             'project_roles': 'jira-project-role'}
    return [{'name': b['name'], 'resource_type': kinds[kind]} for kind in kinds for b in bindings[kind].values()]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    docs, errors = validate(args.root)
    if errors: raise SystemExit('; '.join(errors))
    generated = generate(docs)
    args.output.write_text(json.dumps(generated, indent=2) + '\n')
    print(json.dumps({'identifiers_requiring_registration': identifiers(generated)}, indent=2))
