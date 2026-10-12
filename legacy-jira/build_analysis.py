#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import yaml

import os
BASE = Path(os.environ['PASCODE_JIRA_ROOT']).resolve()
import json as _context_json
_context_file = os.environ.get('PASCODE_LEGACY_CONTEXT')
CONTEXT = _context_json.loads(Path(_context_file).read_text()) if _context_file else {}
CONFIG = BASE / 'config'
ANALYSIS = Path(os.environ.get('PASCODE_ANALYSIS_OUTPUT', BASE / 'analysis'))

files = {
    'projects': CONFIG / 'projects.yaml',
    'permission_schemes': CONFIG / 'permission-schemes.yaml',
    'workflows': CONFIG / 'workflow-definitions.yaml',
    'boards': CONFIG / 'board-filters.yaml',
    'automation': CONFIG / 'automation-triggers.yaml',
    'service_accounts': CONFIG / 'service-account-registry.yaml',
    'transition_matrix': CONFIG / 'transition-control-matrix.yaml',
    'audit': CONFIG / 'audit-observability.yaml',
    'safety': CONFIG / 'final-safety-architecture.yaml',
}

def load(p):
    return yaml.safe_load(p.read_text())

projects_doc = load(files['projects'])
perm_doc = load(files['permission_schemes'])
work_doc = load(files['workflows'])
board_doc = load(files['boards'])
auto_doc = load(files['automation'])
sa_doc = load(files['service_accounts'])
matrix_doc = load(files['transition_matrix'])
audit_doc = load(files['audit'])
safety_doc = load(files['safety'])

projects = projects_doc['projects']
permission_schemes = perm_doc['permission_schemes']
workflows = work_doc['workflow_definitions']
boards = board_doc['board_filters']
automations = auto_doc['automation_triggers']
service_accounts = sa_doc['service_account_registry']
transition_matrix = matrix_doc['transition_control_matrix']

# ---------- dependency graph ----------
nodes = []
edges = []

def add_node(nid, ntype, source):
    nodes.append({'id': nid, 'type': ntype, 'source': source})

def add_edge(src, rel, dst, source):
    edges.append({'source': src, 'relation': rel, 'target': dst, 'source_file': source})

for pname in permission_schemes:
    add_node(f'permission_scheme:{pname}', 'permission_scheme', 'permission-schemes.yaml')
for wname in workflows:
    add_node(f'workflow_scheme:{wname}', 'workflow_scheme', 'workflow-definitions.yaml')
for bname in boards:
    add_node(f'board_filter:{bname}', 'board_filter', 'board-filters.yaml')
for aname in automations:
    add_node(f'automation:{aname}', 'automation', 'automation-triggers.yaml')
for sname in service_accounts:
    add_node(f'service_account:{sname}', 'service_account', 'service-account-registry.yaml')

for p in projects:
    pkey = p['key']
    jira_key = p.get('jira_key', pkey)
    add_node(f'project:{jira_key}', 'project', 'projects.yaml')
    add_node(f'plane:{p["plane"]}', 'plane', 'projects.yaml')
    add_node(f'category:{p["category"]}', 'category', 'projects.yaml')
    add_edge(f'project:{jira_key}', 'in_plane', f'plane:{p["plane"]}', 'projects.yaml')
    add_edge(f'project:{jira_key}', 'in_category', f'category:{p["category"]}', 'projects.yaml')
    add_edge(f'project:{jira_key}', 'uses_permission_scheme', f'permission_scheme:{p["permission_scheme"]}', 'projects.yaml')
    add_edge(f'project:{jira_key}', 'uses_workflow_scheme', f'workflow_scheme:{p["workflow_scheme"]}', 'projects.yaml')
    if p.get('issue_security'):
        sec = p['issue_security']
        add_node(f'issue_security:{sec}', 'issue_security', 'projects.yaml')
        add_edge(f'project:{jira_key}', 'uses_issue_security', f'issue_security:{sec}', 'projects.yaml')

for wname, wdef in workflows.items():
    for s in wdef.get('states', []):
        add_node(f'state:{wname}:{s}', 'state', 'workflow-definitions.yaml')
        add_edge(f'workflow_scheme:{wname}', 'has_state', f'state:{wname}:{s}', 'workflow-definitions.yaml')
    for t in wdef.get('transitions', []):
        add_node(f'transition:{wname}:{t}', 'transition', 'workflow-definitions.yaml')
        add_edge(f'workflow_scheme:{wname}', 'has_transition', f'transition:{wname}:{t}', 'workflow-definitions.yaml')
    for guard in wdef.get('guards', []):
        gid = f'guard:{wname}:{guard}'
        add_node(gid, 'guard', 'workflow-definitions.yaml')
        add_edge(f'workflow_scheme:{wname}', 'has_guard', gid, 'workflow-definitions.yaml')

for sa, cfg in service_accounts.items():
    for scope in cfg.get('oauth_scopes', []):
        add_node(f'scope:{scope}', 'scope', 'service-account-registry.yaml')
        add_edge(f'service_account:{sa}', 'has_scope', f'scope:{scope}', 'service-account-registry.yaml')
    for role in cfg.get('roles', []):
        add_node(f'role:{role}', 'role', 'service-account-registry.yaml')
        add_edge(f'service_account:{sa}', 'has_role', f'role:{role}', 'service-account-registry.yaml')

# ---------- transitive closures ----------
project_map = {p.get('jira_key', p['key']): p for p in projects}
all_project_keys = set(project_map.keys())

restricted_projects = [k for k, p in project_map.items() if p['permission_scheme'] == 'restricted_sensitive']

high_risk_actions = {
    row['status_move']: (row['human_required'], row['agent_allowed'])
    for row in transition_matrix
}

scope_to_capability = {
    'read:jira-work': ['read_issues'],
    'write:jira-work': ['create_issue', 'edit_issue', 'comment', 'link_issue', 'transition_non_gated'],
    'read:jira-user': ['read_user_profiles'],
    'manage:jira-webhook': ['create_webhook', 'delete_webhook', 'update_webhook'],
    'read:servicedesk-request': ['read_jsm_requests'],
    'write:servicedesk-request': ['update_jsm_requests'],
    'manage:servicedesk-customer': ['manage_jsm_customers'],
    'read:ops-alert:jira-service-management': ['read_ops_alerts'],
    'write:ops-alert:jira-service-management': ['write_ops_alerts'],
    'manage:jira-configuration': ['manage_global_jira_configuration'],
    'manage:jira-project': ['manage_project_configuration'],
}

sa_effective = {}
for sa, cfg in service_accounts.items():
    caps = []
    for s in cfg.get('oauth_scopes', []):
        caps.extend(scope_to_capability.get(s, [f'unknown_scope:{s}']))
    caps = sorted(set(caps))
    denied = set(cfg.get('project_access', {}).get('denied', []))
    can_finalize = any(x in caps for x in ['manage_global_jira_configuration', 'manage_project_configuration'])
    sa_effective[sa] = {
        'capabilities': caps,
        'denied_projects': sorted(denied),
        'can_finalize_high_risk': can_finalize,
        'api_token': cfg.get('api_token', {})
    }

# JQL/automation field dependencies and referenced projects
field_dependencies = []
project_ref_pat = re.compile(r'project\s*=\s*([A-Za-z0-9\-]+)')
for bname, bcfg in boards.items():
    jql = bcfg.get('jql', '')
    m = project_ref_pat.search(jql)
    pref = m.group(1) if m else None
    fields = []
    if 'severity' in jql:
        fields.append('severity')
    if 'SLA Due Date' in jql:
        fields.append('SLA Due Date')
    if 'Customer Tier' in jql:
        fields.append('Customer Tier')
    field_dependencies.append({'source': f'board:{bname}', 'project_ref': pref, 'fields': sorted(set(fields))})

for aname, acfg in automations.items():
    fields = list((acfg.get('if') or {}).keys())
    target = None
    for action in acfg.get('then', []):
        if isinstance(action, dict) and 'create_linked_issue' in action:
            target = action['create_linked_issue'].get('project')
    field_dependencies.append({'source': f'automation:{aname}', 'project_ref': target, 'fields': sorted(set(fields))})

transitive = {
    'restricted_projects': restricted_projects,
    'high_risk_actions': high_risk_actions,
    'service_account_effective_access': sa_effective,
    'field_and_project_dependencies': field_dependencies,
    'scope_capability_map': scope_to_capability,
}

# ---------- contradictions ----------
conflicts = []
warnings = []

# Missing scheme/workflow refs
for p in projects:
    jk = p.get('jira_key', p['key'])
    if p['permission_scheme'] not in permission_schemes:
        conflicts.append({'type': 'missing_permission_scheme', 'project': jk, 'value': p['permission_scheme']})
    if p['workflow_scheme'] not in workflows:
        conflicts.append({'type': 'missing_workflow_scheme', 'project': jk, 'value': p['workflow_scheme']})

# Project key validity and uniqueness
seen = set()
for p in projects:
    jk = p.get('jira_key', p['key'])
    if not re.match(r'^[A-Z][A-Z0-9]+$', jk):
        conflicts.append({'type': 'invalid_jira_key', 'project': p['key'], 'jira_key': jk})
    if jk in seen:
        conflicts.append({'type': 'duplicate_jira_key', 'jira_key': jk})
    seen.add(jk)

# Restricted projects must have issue security
for p in projects:
    if p['permission_scheme'] == 'restricted_sensitive' and not p.get('issue_security'):
        conflicts.append({'type': 'restricted_project_missing_issue_security', 'project': p.get('jira_key', p['key'])})

# Board and automation project refs must resolve to jira_key
for dep in field_dependencies:
    pref = dep['project_ref']
    if not pref:
        continue
    if pref not in all_project_keys:
        warnings.append({
            'type': 'project_reference_not_jira_key',
            'source': dep['source'],
            'project_ref': pref,
            'known_jira_keys': sorted(all_project_keys)
        })

# Transition matrix must enforce human-required for high-risk endings
high_risk_labels = {'Approve Change', 'Close Incident', 'Close Vulnerability', 'Mark Paid (FIN)'}
for row in transition_matrix:
    if row['status_move'] in high_risk_labels and (not row['human_required'] or row['agent_allowed']):
        conflicts.append({'type': 'high_risk_transition_not_protected', 'row': row})

# Service account token expiration presence
for sa, cfg in service_accounts.items():
    exp = (cfg.get('api_token') or {}).get('expiration_date')
    if not exp:
        conflicts.append({'type': 'missing_api_token_expiration', 'service_account': sa})

conflicts_report = {
    'blockers': conflicts,
    'warnings': warnings,
    'summary': {
        'blocker_count': len(conflicts),
        'warning_count': len(warnings),
    }
}

# ---------- apply order ----------
apply_order = {
    'steps': [
        {
            'order': 1,
            'name': 'global-groups-and-roles',
            'inputs': ['permission-schemes.yaml', 'service-account-registry.yaml'],
            'preconditions': ['jira site reachable', 'admin credentials valid'],
            'postconditions': ['groups exist', 'project roles baseline available']
        },
        {
            'order': 2,
            'name': 'permission-schemes',
            'inputs': ['permission-schemes.yaml'],
            'preconditions': ['groups/roles created'],
            'postconditions': ['all permission schemes created']
        },
        {
            'order': 3,
            'name': 'workflows-and-workflow-schemes',
            'inputs': ['workflow-definitions.yaml', 'transition-control-matrix.yaml'],
            'preconditions': ['issue types available'],
            'postconditions': ['workflows and guards created']
        },
        {
            'order': 4,
            'name': 'projects',
            'inputs': ['projects.yaml'],
            'preconditions': ['permission schemes/workflow schemes exist'],
            'postconditions': ['all projects created and bound to schemes']
        },
        {
            'order': 5,
            'name': 'boards-filters-queues',
            'inputs': ['board-filters.yaml'],
            'preconditions': ['projects and required fields exist'],
            'postconditions': ['filters/boards/queues created']
        },
        {
            'order': 6,
            'name': 'automation-and-webhooks',
            'inputs': ['automation-triggers.yaml', 'final-safety-architecture.yaml'],
            'preconditions': ['projects/fields/roles available'],
            'postconditions': ['automation active and gated']
        },
        {
            'order': 7,
            'name': 'service-accounts',
            'inputs': ['service-account-registry.yaml'],
            'preconditions': ['apps provisioned'],
            'postconditions': ['scopes, project access, tokens aligned']
        },
        {
            'order': 8,
            'name': 'audit-observability',
            'inputs': ['audit-observability.yaml'],
            'preconditions': ['automation running'],
            'postconditions': ['logs exported and retention enforced']
        }
    ]
}

# ---------- drift report ----------
drift = {
    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    'scope': CONTEXT.get('site_scope', 'unconfigured'),
    'desired_project_keys': sorted(all_project_keys),
    'status': 'not_observed',
    'live_project_keys': None,
    'missing_in_jira': None,
    'unexpected_in_jira': None,
    'alignment': None,
    'note': 'Static analysis makes no live Jira request.',
}

# Explicit legacy evidence input; never label a static sample as a live probe.
if 'historical_project_keys' in CONTEXT:
    sample = CONTEXT['historical_project_keys']
    drift.update(live_project_keys=sample,
                 missing_in_jira=sorted(set(all_project_keys) - set(sample)),
                 unexpected_in_jira=sorted(set(sample) - set(all_project_keys)),
                 alignment=set(all_project_keys) == set(sample),
                 status='historical_sample', evidence_kind='static_legacy_sample',
                 note='Historical sample supplied by the instance; no live Jira request.')

ANALYSIS.mkdir(parents=True, exist_ok=True)
(ANALYSIS / 'dependency-graph.json').write_text(json.dumps({'nodes': nodes, 'edges': edges}, indent=2))
(ANALYSIS / 'transitive-closures.json').write_text(json.dumps(transitive, indent=2))
(ANALYSIS / 'conflicts.json').write_text(json.dumps(conflicts_report, indent=2))
(ANALYSIS / 'apply-order.json').write_text(json.dumps(apply_order, indent=2))
(ANALYSIS / 'drift-report.json').write_text(json.dumps(drift, indent=2))

print('wrote:', [
    'dependency-graph.json',
    'transitive-closures.json',
    'conflicts.json',
    'apply-order.json',
    'drift-report.json',
])
print('blockers:', len(conflicts), 'warnings:', len(warnings))
