#!/usr/bin/env python3
from pathlib import Path
import copy
import yaml

import os
BASE = Path(os.environ['PASCODE_JIRA_ROOT']).resolve()
import json as _context_json
_context_file = os.environ.get('PASCODE_LEGACY_CONTEXT')
CONTEXT = _context_json.loads(Path(_context_file).read_text()) if _context_file else {}
CONFIG = BASE / 'config'
OUT = Path(os.environ.get('PASCODE_MAPPED_OUTPUT', BASE / 'mapped'))
OUT.mkdir(parents=True, exist_ok=True)

def load(name):
    return yaml.safe_load((CONFIG / name).read_text())

def dump(name, data):
    (OUT / name).write_text(yaml.safe_dump(data, sort_keys=False, width=120))

# Mapping definitions
file_steps = {
    'projects.yaml': {'step': 4, 'phase': 'projects', 'action': 'create and bind schemes/security'},
    'permission-schemes.yaml': {'step': 2, 'phase': 'permission-schemes', 'action': 'create/update and grant mappings'},
    'workflow-definitions.yaml': {'step': 3, 'phase': 'workflows', 'action': 'create workflows, transitions, guards, schemes'},
    'board-filters.yaml': {'step': 5, 'phase': 'boards-filters', 'action': 'create filters/boards/queues/swimlanes'},
    'automation-triggers.yaml': {'step': 6, 'phase': 'automation', 'action': 'create rules and webhook-triggered actions'},
    'service-account-registry.yaml': {'step': 7, 'phase': 'service-accounts', 'action': 'reconcile app scopes/access/tokens'},
    'transition-control-matrix.yaml': {'step': 6, 'phase': 'governance-overlays', 'action': 'enforce HITL transition controls'},
    'audit-observability.yaml': {'step': 8, 'phase': 'audit-observability', 'action': 'enable logs/export/retention'},
    'final-safety-architecture.yaml': {'step': 6, 'phase': 'safety-policy', 'action': 'enforce agent/human action boundaries'},
}

# projects.yaml
p = load('projects.yaml')
p_out = {
    'implementation': file_steps['projects.yaml'],
    'projects': []
}
for item in p.get('projects', []):
    it = copy.deepcopy(item)
    it['implementation_step'] = 4
    it['implementation_action'] = 'create_project_then_bind_permission_workflow_and_issue_security'
    p_out['projects'].append(it)
dump('projects.yaml', p_out)

# permission-schemes.yaml
ps = load('permission-schemes.yaml')
ps_out = {'implementation': file_steps['permission-schemes.yaml'], 'permission_schemes': {}}
for name, cfg in ps.get('permission_schemes', {}).items():
    c = copy.deepcopy(cfg)
    c['_implementation_step'] = 2
    c['_implementation_action'] = 'create_or_update_permission_scheme_and_grants'
    ps_out['permission_schemes'][name] = c
dump('permission-schemes.yaml', ps_out)

# workflow-definitions.yaml
w = load('workflow-definitions.yaml')
w_out = {'implementation': file_steps['workflow-definitions.yaml'], 'workflow_definitions': {}}
for name, cfg in w.get('workflow_definitions', {}).items():
    c = copy.deepcopy(cfg)
    c['_implementation_step'] = 3
    c['_implementation_action'] = 'create_workflow_define_transitions_attach_guards_map_to_scheme'
    w_out['workflow_definitions'][name] = c
dump('workflow-definitions.yaml', w_out)

# board-filters.yaml
b = load('board-filters.yaml')
b_out = {'implementation': file_steps['board-filters.yaml'], 'board_filters': {}}
for name, cfg in b.get('board_filters', {}).items():
    c = copy.deepcopy(cfg)
    c['_implementation_step'] = 5
    c['_implementation_action'] = 'create_saved_filter_then_board_or_queue'
    b_out['board_filters'][name] = c
dump('board-filters.yaml', b_out)

# automation-triggers.yaml
a = load('automation-triggers.yaml')
a_out = {'implementation': file_steps['automation-triggers.yaml'], 'automation_triggers': {}}
for name, cfg in a.get('automation_triggers', {}).items():
    c = copy.deepcopy(cfg)
    c['_implementation_step'] = 6
    c['_implementation_action'] = 'create_automation_rule_with_conditions_and_actions'
    a_out['automation_triggers'][name] = c
dump('automation-triggers.yaml', a_out)

# service-account-registry.yaml
s = load('service-account-registry.yaml')
s_out = {'implementation': file_steps['service-account-registry.yaml'], 'service_account_registry': {}}
for name, cfg in s.get('service_account_registry', {}).items():
    c = copy.deepcopy(cfg)
    c['_implementation_step'] = 7
    c['_implementation_action'] = 'reconcile_account_scope_project_access_and_token_policy'
    s_out['service_account_registry'][name] = c
dump('service-account-registry.yaml', s_out)

if CONTEXT.get('include_auth_routing', False):
    s_out['user_accounts'] = copy.deepcopy(s.get('user_accounts', {}))
    dump('service-account-registry.yaml', s_out)
    routing = load('api_auth_routing.yaml')
    routing['implementation'] = {'step': 7, 'phase': 'auth-routing', 'action': 'select identity by endpoint family'}
    dump('api_auth_routing.yaml', routing)

# transition-control-matrix.yaml
t = load('transition-control-matrix.yaml')
t_out = {'implementation': file_steps['transition-control-matrix.yaml'], 'transition_control_matrix': []}
for item in t.get('transition_control_matrix', []):
    it = copy.deepcopy(item)
    it['implementation_step'] = 6
    it['implementation_action'] = 'enforce_transition_permission_and_guard'
    t_out['transition_control_matrix'].append(it)
dump('transition-control-matrix.yaml', t_out)

# audit-observability.yaml
aud = load('audit-observability.yaml')
aud_out = copy.deepcopy(aud)
aud_out['implementation'] = file_steps['audit-observability.yaml']
dump('audit-observability.yaml', aud_out)

# final-safety-architecture.yaml
f = load('final-safety-architecture.yaml')
f_out = copy.deepcopy(f)
f_out['implementation'] = file_steps['final-safety-architecture.yaml']
dump('final-safety-architecture.yaml', f_out)

# manifest
manifest = {
    'mapped_directory': str(OUT) if CONTEXT.get('absolute_mapped_manifest', False) else 'jira-as-code/mapped',
    'generated_files': sorted([p.name for p in OUT.glob('*.yaml')]),
    'notes': 'Each file is a mapped copy with implementation-step metadata per configuration item.'
}
dump('_manifest.yaml', manifest)
print('\n'.join(manifest['generated_files']))
