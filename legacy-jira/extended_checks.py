#!/usr/bin/env python3
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
import yaml

import os
BASE = Path(os.environ['PASCODE_JIRA_ROOT']).resolve()
import json as _context_json
_context_file = os.environ.get('PASCODE_LEGACY_CONTEXT')
CONTEXT = _context_json.loads(Path(_context_file).read_text()) if _context_file else {}
CONFIG = BASE / 'config'
A = Path(os.environ.get('PASCODE_ANALYSIS_OUTPUT', BASE / 'analysis'))

FILES = {
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

def load(path):
    return yaml.safe_load(path.read_text())

def parse_arrow(t):
    if '->' not in t:
        return None, None
    a,b=t.split('->',1)
    return a.strip(), b.strip()

pdoc = load(FILES['projects'])
psdoc = load(FILES['permission_schemes'])
wdoc = load(FILES['workflows'])
bdoc = load(FILES['boards'])
adoc = load(FILES['automation'])
sadoc = load(FILES['service_accounts'])
tdoc = load(FILES['transition_matrix'])
audoc = load(FILES['audit'])
sfdoc = load(FILES['safety'])

projects = pdoc['projects']
perm = psdoc['permission_schemes']
work = wdoc['workflow_definitions']
boards = bdoc['board_filters']
autom = adoc['automation_triggers']
svc = sadoc['service_account_registry']
matrix = tdoc['transition_control_matrix']

errors = []
warnings = []
checks = []

def ok(name, detail=''):
    checks.append({'check': name, 'status': 'pass', 'detail': detail})

def fail(name, detail):
    checks.append({'check': name, 'status': 'fail', 'detail': detail})
    errors.append({'check': name, 'detail': detail})

def warn(name, detail):
    checks.append({'check': name, 'status': 'warn', 'detail': detail})
    warnings.append({'check': name, 'detail': detail})

# 1. YAML structure sanity
required_roots = [
    ('projects.yaml', 'projects', pdoc),
    ('permission-schemes.yaml', 'permission_schemes', psdoc),
    ('workflow-definitions.yaml', 'workflow_definitions', wdoc),
    ('board-filters.yaml', 'board_filters', bdoc),
    ('automation-triggers.yaml', 'automation_triggers', adoc),
    ('service-account-registry.yaml', 'service_account_registry', sadoc),
    ('transition-control-matrix.yaml', 'transition_control_matrix', tdoc),
]
for fname, root, doc in required_roots:
    if root not in doc:
        fail('root-key', f'{fname} missing root key {root}')
    else:
        ok('root-key', f'{fname} has root {root}')

# 2. Project key validation + uniqueness
jira_keys = []
for p in projects:
    jk = p.get('jira_key', p['key'])
    jira_keys.append(jk)
    if not re.match(r'^[A-Z][A-Z0-9]+$', jk):
        fail('project-key-format', f'invalid jira_key {jk} for {p["key"]}')
if len(set(jira_keys)) != len(jira_keys):
    fail('project-key-unique', 'duplicate jira_key detected')
else:
    ok('project-key-unique', 'all jira_key values unique')

# 3. Cross-file references
perm_names = set(perm.keys())
wf_names = set(work.keys())
for p in projects:
    jk = p.get('jira_key', p['key'])
    if p['permission_scheme'] not in perm_names:
        fail('project->permission-scheme', f'{jk} references unknown permission scheme {p["permission_scheme"]}')
    if p['workflow_scheme'] not in wf_names:
        fail('project->workflow-scheme', f'{jk} references unknown workflow scheme {p["workflow_scheme"]}')
ok('cross-file-refs', 'project scheme/workflow references resolved') if not errors else None

# 4. Restricted-project hard rule
restricted = [p for p in projects if p['permission_scheme']=='restricted_sensitive']
restricted_keys = sorted([p.get('jira_key', p['key']) for p in restricted])
expected_restricted = ['FIN','LEGAL','PEOPLE']
if restricted_keys != expected_restricted:
    fail('restricted-project-set', f'expected {expected_restricted}, got {restricted_keys}')
else:
    ok('restricted-project-set', str(restricted_keys))

for p in restricted:
    if not p.get('issue_security'):
        fail('restricted-issue-security', f'{p.get("jira_key", p["key"])} missing issue_security')
if not any(c['check']=='restricted-issue-security' and c['status']=='fail' for c in checks):
    ok('restricted-issue-security', 'all restricted projects define issue_security')

# 5. Workflow integrity (transition states exist + reachability)
for wname, wcfg in work.items():
    states = set()
    if 'states' in wcfg:
        states.update(wcfg['states'])
    if 'incident' in wcfg:
        states.update(wcfg['incident'].get('states', []))
    if 'change' in wcfg:
        states.update(wcfg['change'].get('states', []))

    trans = []
    trans.extend(wcfg.get('transitions', []))
    trans.extend(wcfg.get('incident', {}).get('transitions', []))
    trans.extend(wcfg.get('change', {}).get('transitions', []))

    adj = {s:set() for s in states}
    indeg = {s:0 for s in states}
    for t in trans:
        a,b = parse_arrow(t)
        if not a or not b:
            fail('workflow-transition-format', f'{wname} has invalid transition {t}')
            continue
        if a not in states or b not in states:
            fail('workflow-transition-state-ref', f'{wname} transition {t} references missing state')
            continue
        adj[a].add(b)
        indeg[b]+=1

    if states:
        starts = [s for s in states if indeg[s]==0]
        if not starts:
            warn('workflow-start-state', f'{wname} has no start state (all states have incoming edges)')
        else:
            seen=set(starts)
            stack=list(starts)
            while stack:
                n=stack.pop()
                for nb in adj[n]:
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            unreachable = sorted(states-seen)
            if unreachable:
                warn('workflow-reachability', f'{wname} unreachable states: {unreachable}')

# 6. Board/automation project ref checks
known = set(jira_keys)
project_ref_re = re.compile(r'project\s*=\s*([A-Za-z0-9\-]+)')
for bname, bcfg in boards.items():
    jql = bcfg.get('jql','')
    m = project_ref_re.search(jql)
    if m:
        pref = m.group(1)
        if pref not in known:
            fail('board-project-ref', f'{bname} references unknown jira_key {pref}')
for aname, acfg in autom.items():
    for action in acfg.get('then', []):
        if isinstance(action, dict) and 'create_linked_issue' in action:
            pref = action['create_linked_issue'].get('project')
            if pref and pref not in known:
                fail('automation-project-ref', f'{aname} references unknown jira_key {pref}')
if not any(c['check'] in ('board-project-ref','automation-project-ref') and c['status']=='fail' for c in checks):
    ok('jql-and-automation-project-refs', 'all project references resolve to jira_key set')

# 7. Service account policy checks
required_sa_keys = {'purpose','roles','api_token','oauth_scopes'}
allowed_project_roles = {'Project Admins', 'Leads/Approvers', 'Contributors', 'Viewers', 'Agents (Bot Users)'}
for sname, scfg in svc.items():
    missing = sorted(k for k in required_sa_keys if k not in scfg)
    if missing:
        fail('service-account-shape', f'{sname} missing keys {missing}')
    token = scfg.get('api_token', {})
    if token.get('type') != 'API':
        fail('service-account-token-type', f'{sname} token type is not API')
    exp = token.get('expiration_date')
    try:
        d = datetime.strptime(exp, '%Y-%m-%d').date()
        if d <= date.today():
            fail('service-account-token-expiry', f'{sname} token expiration not in future: {exp}')
    except Exception:
        fail('service-account-token-expiry-format', f'{sname} expiration_date invalid: {exp}')

    # membership invariant checks
    membership_required = bool(scfg.get('project_membership_required', False))
    bindings = scfg.get('project_role_bindings', {}) or {}
    if membership_required and not bindings:
        fail('service-account-membership-bindings', f'{sname} requires membership but has no project_role_bindings')
        continue

    # Gather expected allowed projects from access model
    expected_allowed = set()
    pa = scfg.get('project_access', {}) or {}
    for k in ('contributor', 'agent', 'read_only', 'limited'):
        vals = pa.get(k, [])
        if isinstance(vals, list):
            expected_allowed.update(vals)
    access = scfg.get('access', {}) or {}
    vals = access.get('contributor', [])
    if isinstance(vals, list):
        expected_allowed.update(vals)
    scope_limit = scfg.get('scope_limit', {}) or {}
    write_projects = (scope_limit.get('write_projects') or [])
    if isinstance(write_projects, list):
        expected_allowed.update(write_projects)
    # admin_temporary_via_ci implies full project admin coverage
    if pa.get('admin_temporary_via_ci') is True:
        expected_allowed.update(known)

    denied_projects = set(pa.get('denied', []) if isinstance(pa.get('denied', []), list) else [])

    # Validate binding keys and roles
    for proj, role in bindings.items():
        if proj not in known:
            fail('service-account-membership-project-key', f'{sname} binding uses unknown project key {proj}')
        if role not in allowed_project_roles:
            fail('service-account-membership-role', f'{sname} binding for {proj} uses invalid role {role}')
        if proj in denied_projects:
            fail('service-account-membership-denied-conflict', f'{sname} binds denied project {proj}')

    if membership_required:
        missing_bindings = sorted(expected_allowed - set(bindings.keys()))
        if missing_bindings:
            fail('service-account-membership-coverage', f'{sname} missing bindings for allowed projects {missing_bindings}')
        else:
            ok('service-account-membership-coverage', f'{sname} has bindings for all allowed projects')

# restricted deny set check for automation app
automation_account = CONTEXT['automation_account']
ja = svc.get(automation_account, {})
denied = set(ja.get('project_access', {}).get('denied', []))
if {'FIN','LEGAL','PEOPLE'}.issubset(denied):
    ok('restricted-deny-coverage', f'{automation_account} denies FIN/LEGAL/PEOPLE')
else:
    fail('restricted-deny-coverage', f'{automation_account} denied set missing restricted projects: {sorted(denied)}')

# 8. Transition matrix safety
required = {'Approve Change','Close Incident','Close Vulnerability','Mark Paid (FIN)'}
seen = {r['status_move'] for r in matrix}
if not required.issubset(seen):
    fail('transition-matrix-coverage', f'missing rows: {sorted(required-seen)}')
for r in matrix:
    if r['status_move'] in required and (not r.get('human_required') or r.get('agent_allowed')):
        fail('transition-matrix-safety', f"{r['status_move']} violates human_required/agent_allowed")
if not any(c['check']=='transition-matrix-safety' and c['status']=='fail' for c in checks):
    ok('transition-matrix-safety', 'high-risk moves require human and block agent')

# 9. Audit and safety policy sanity
ret = audoc.get('audit_observability', {}).get('retention', {}).get('minimum_days', 0)
if ret >= 90:
    ok('audit-retention', f'minimum_days={ret}')
else:
    fail('audit-retention', f'minimum_days too low: {ret}')

humans = set(sfdoc.get('final_safety_architecture', {}).get('humans', []))
agents = set(sfdoc.get('final_safety_architecture', {}).get('agents', []))
for need in ['Approve','Close','Release','Pay','Sign']:
    if need not in humans:
        fail('safety-humans-list', f'missing human action {need}')
for forbid in ['Approve','Close','Release','Pay','Sign']:
    if forbid in agents:
        fail('safety-agents-list', f'agent list contains forbidden action {forbid}')
if not any(c['check'] in ('safety-humans-list','safety-agents-list') and c['status']=='fail' for c in checks):
    ok('safety-action-separation', 'humans vs agents action split is valid')

report = {
    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    'summary': {
        'total_checks': len(checks),
        'failures': len(errors),
        'warnings': len(warnings)
    },
    'checks': checks,
    'errors': errors,
    'warnings': warnings,
}

A.mkdir(parents=True, exist_ok=True)
(A / 'consistency-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report['summary'], indent=2))
