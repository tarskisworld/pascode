"""Thin on-demand deployment: discover inputs, Terraform, then Jira REST mappings."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from jsonschema import Draft202012Validator
from adapters import MappingError, workflow_request, work_type_scheme_request, workflow_scheme_request, scheme_association
from runner import validate, terraform_configuration
from worker import load


class DeploymentError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DeploymentError('Jira API redirect refused')


class Jira:
    def __init__(self):
        if os.environ.get('PASCODE_AUTH_MODE') not in {'api_token_bootstrap', 'api_service_account_override'}:
            raise DeploymentError('select PASCODE_AUTH_MODE explicitly; this Terraform provider uses email/API-token authentication')
        self.base = os.environ.get('JIRA_API_BASE_URL', '').rstrip('/')
        parsed = urlparse(self.base)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise DeploymentError('a credential-free HTTPS Jira API base URL is required')
        if not (parsed.hostname == 'api.atlassian.com' and re.fullmatch(r'/ex/jira/[a-zA-Z0-9-]+', parsed.path) or
                (parsed.hostname or '').endswith('.atlassian.net') and not parsed.path):
            raise DeploymentError('unsupported Jira Cloud API base URL')
        email = os.environ.get('JIRA_API_EMAIL'); token = os.environ.get('JIRA_API_TOKEN')
        if not email or not token:
            raise DeploymentError('JIRA_API_EMAIL and runtime JIRA_API_TOKEN are required')
        self.auth = 'Basic ' + base64.b64encode(f'{email}:{token}'.encode()).decode()
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, query=None):
        if not path.startswith('/rest/api/3/'):
            raise DeploymentError('unsupported Jira API path')
        url = self.base + path + ('?' + urlencode(query, doseq=True) if query else '')
        payload = json.dumps(body).encode() if body is not None else None
        request = Request(url, data=payload, method=method, headers={
            'Authorization': self.auth, 'Accept': 'application/json', 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=60) as response:
                data = response.read()
                if response.status == 202:
                    raise DeploymentError(f'Jira accepted an asynchronous operation; completion tracking is required: {method} {path}')
                return json.loads(data) if data else None
        except HTTPError as exc:
            raise DeploymentError(f'Jira HTTP {exc.code}: {method} {path}') from None
        except URLError:
            raise DeploymentError(f'Jira connection failed: {method} {path}') from None


def pages(api, path, query=None):
    values = []; start = 0
    while True:
        result = api.request('GET', path, query={**(query or {}), 'startAt': start, 'maxResults': 100})
        batch = result.get('values', [])
        values.extend(batch)
        if result.get('isLast') or len(values) >= result.get('total', float('inf')):
            return values
        if not batch:
            raise DeploymentError(f'incomplete pagination: {path}')
        start += len(batch)


def one(items, label):
    if len(items) > 1:
        raise DeploymentError(f'ambiguous remote binding: {label}; provide a native name or ID')
    return items[0] if items else None


def normalized_type(name):
    return re.sub(r'[^a-z0-9]', '', re.sub(r'^\[System\]\s*', '', name).lower())


def find_type(name, types, native_name=None):
    global_types = [t for t in types if t.get('scope', {}).get('type', 'GLOBAL') == 'GLOBAL']
    matches = [t for t in global_types if t['name'] == (native_name or name)]
    if not matches and native_name is None:
        matches = [t for t in global_types if normalized_type(t['name']) == normalized_type(name)]
    return one(matches, 'work type ' + name)


def status_bindings(statuses):
    result = {}
    for status in statuses:
        if status.get('scope', {}).get('type', 'GLOBAL') != 'GLOBAL':
            continue
        name = status['name']
        if name in result:
            raise DeploymentError(f'ambiguous global status: {name}')
        result[name] = {'id': str(status['id']), 'category': status['statusCategory']}
    return result


def select(documents, keys):
    docs = copy.deepcopy(documents)
    projects = docs['projects']['projects']
    keys = keys or [p['key'] for p in projects]
    if set(keys) - {p['key'] for p in projects}:
        raise DeploymentError('unknown selected project key')
    docs['projects']['projects'] = [p for p in projects if p['key'] in keys]
    schemes = docs['workflow-definitions']['workflow_schemes']
    names = {p['work_type_scheme'] for p in docs['projects']['projects']}
    docs['workflow-definitions']['workflow_schemes'] = {n: s for n, s in schemes.items() if n in names}
    required = {n for s in docs['workflow-definitions']['workflow_schemes'].values() for n in [s['default'], *s['overrides'].values()]}
    docs['workflow-definitions']['workflow_definitions'] = {n: w for n, w in docs['workflow-definitions']['workflow_definitions'].items() if n in required}
    return docs


def source_digest(docs, bindings):
    return hashlib.sha256(json.dumps([docs, bindings], sort_keys=True).encode()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def mapper_digest():
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root / n).read_bytes() for n in
        ('deployment.py', 'adapters.py', 'runner.py', 'bindings.schema.json'))).hexdigest()


def terraform_bindings(prepared, state):
    """Use successful Terraform state for IDs, without rediscovering the whole site."""
    selected, resolved, variables, imports, plan = copy.deepcopy(prepared)
    keys = {p['key'] for p in selected['projects']['projects']}
    types = {n for p in selected['projects']['projects'] for n in p['work_types']}
    resolved['projects'] = {}; resolved['issue_types'] = {}
    for resource in state.get('resources', []):
        if resource.get('mode') != 'managed': continue
        for instance in resource.get('instances', []):
            key = instance.get('index_key'); attrs = instance.get('attributes', {})
            if instance.get('deposed') or not attrs.get('id'): continue
            if resource['type'] == 'jira_project' and resource['name'] == 'projects' and key in keys:
                if attrs.get('key') != key: raise DeploymentError('Terraform project binding mismatch')
                resolved['projects'][key] = str(attrs['id'])
                if variables['permission_scheme_ids'].get(key) is None:
                    variables['permission_scheme_ids'][key] = attrs.get('permission_scheme')
            elif resource['type'] == 'jira_issue_type' and resource['name'] == 'work_types' and key in types:
                resolved['issue_types'][key] = {'id': str(attrs['id']), 'is_subtask': attrs['is_subtask']}
    if set(resolved['projects']) != keys or set(resolved['issue_types']) != types:
        raise DeploymentError('successful Terraform state must contain every selected project and work type')
    for deferred in plan['deferred_permission_assignments']:
        deferred['observed_scheme_id'] = variables['permission_scheme_ids'][deferred['project']]
    return selected, resolved, variables, imports, plan


def current_workflow(api, name):
    matches = pages(api, '/rest/api/3/workflows/search', {'queryString': name, 'scope': 'GLOBAL'})
    match = one([w for w in matches if w['name'] == name], 'workflow ' + name)
    if not match:
        return None
    full = api.request('POST', '/rest/api/3/workflows', {
        'workflowIds': [match['id']], 'workflowNames': [], 'projectAndIssueTypes': []})
    return one(full.get('workflows', []), 'workflow definition ' + name), full.get('statuses', [])


def semantic_workflow(workflow, statuses):
    names = {str(s['statusReference']): s['name'] for s in statuses}
    categories = {s['name']: s['statusCategory'] for s in statuses}
    transitions = []
    for transition in workflow['transitions']:
        effects = []
        for action in transition.get('actions', []):
            parameters = action.get('parameters', {})
            if action.get('ruleKey') != 'system:update-field' or parameters.get('field') != 'resolution':
                effects.append(['unmodeled', action]); continue
            effects.append(['resolution', parameters.get('value', '')])
        links = [names[str(link['fromStatusReference'])] for link in transition.get('links', [])]
        transitions.append([transition['type'], transition['name'], sorted(links), names[str(transition['toStatusReference'])],
                            effects, transition.get('conditions') or None, transition.get('validators') or []])
    return {'statuses': {names[str(s['statusReference'])]: categories[names[str(s['statusReference'])]] for s in workflow['statuses']},
            'transitions': sorted(transitions, key=lambda t: json.dumps(t, sort_keys=True))}


def workflow_operation(api, definition, binding, statuses, resolutions, validate_remote=False):
    name = binding.get('name')
    if not name:
        raise DeploymentError('workflow native name is required')
    observed = current_workflow(api, name)
    if observed:
        existing, observed_statuses = observed
        names = {str(s['statusReference']): s['name'] for s in observed_statuses}
        if {names[str(s['statusReference'])] for s in existing['statuses']} != set(definition['statuses']):
            raise DeploymentError(f'{name}: status changes require a migration adapter')
        ids = {}
        for t in existing['transitions']:
            if t.get('validators') or t.get('conditions') or any(
                    a.get('ruleKey') != 'system:update-field' or a.get('parameters', {}).get('field') != 'resolution'
                    for a in t.get('actions', [])):
                raise DeploymentError(f'{name}: existing unmodeled workflow rules require explicit mapping')
            if t['type'] == 'INITIAL': signature = ['INITIAL']
            elif t['type'] == 'DIRECTED' and len(t.get('links', [])) == 1:
                signature = [t['name'], names[str(t['links'][0]['fromStatusReference'])], names[str(t['toStatusReference'])]]
            else:
                raise DeploymentError(f'{name}: unsupported existing workflow topology')
            key = json.dumps(signature)
            if key in ids: raise DeploymentError(f'{name}: duplicate observed transition signature')
            ids[key] = str(t['id'])
        expected_keys = {json.dumps(['INITIAL']), *[json.dumps([t['name'], t['from'], t['to']]) for t in definition['transitions']]}
        if set(ids) != expected_keys:
            raise DeploymentError(f'{name}: topology changes require a migration adapter')
        binding = {**binding, 'existing': {'id': existing['id'], 'version': existing['version'], 'transition_ids': ids}}
    request = workflow_request(definition, binding, statuses, resolutions)
    desired = request['body']['workflows'][0]
    if observed and semantic_workflow(existing, observed_statuses) == semantic_workflow(desired, request['body']['statuses']):
        return {'action': 'reuse', 'name': name}
    if observed:
        if 'startPointLayout' in existing: desired['startPointLayout'] = existing['startPointLayout']
        by_name = {names[str(s['statusReference'])]: s for s in existing['statuses']}
        payload_names = {s['statusReference']: s['name'] for s in request['body']['statuses']}
        for s in desired['statuses']:
            old = by_name.get(payload_names[s['statusReference']], {})
            for key in ('layout', 'properties', 'deprecated'):
                if key in old: s[key] = old[key]
        by_id = {str(t['id']): t for t in existing['transitions']}
        for t in desired['transitions']:
            old = by_id[str(t['id'])]
            for key in ('properties', 'triggers', 'description'):
                if key in old: t[key] = old[key]
    if validate_remote:
        validation = request['validation']
        result = api.request(validation['method'], validation['path'], validation['body'])
        if result and result.get('errors'):
            raise DeploymentError(f'{name}: Jira workflow validation failed')
    return {'action': 'update' if observed else 'create', 'name': name, 'request': request}


def resolve(docs, bindings, api, validate_remote=False):
    settings = bindings.get('deployment', {})
    selected = select(docs, settings.get('project_keys'))
    site = api.request('GET', '/rest/api/3/serverInfo')
    if site.get('baseUrl', '').rstrip('/') != docs['site']['site']['base_url'].rstrip('/'):
        raise DeploymentError('authenticated API context does not match the declared site')
    myself = api.request('GET', '/rest/api/3/myself')
    if not myself.get('active'): raise DeploymentError('bootstrap identity is inactive')
    permissions = api.request('GET', '/rest/api/3/mypermissions', query={'permissions': 'ADMINISTER'})
    if not permissions.get('permissions', {}).get('ADMINISTER', {}).get('havePermission'):
        raise DeploymentError('Jira administration permission is required')
    projects = pages(api, '/rest/api/3/project/search')
    types = api.request('GET', '/rest/api/3/issuetype')
    native_schemes = api.request('GET', '/rest/api/3/permissionscheme')['permissionSchemes']
    available_types = {p['key'] for p in api.request('GET', '/rest/api/3/project/type/accessible')}
    statuses = status_bindings(pages(api, '/rest/api/3/statuses/search'))
    resolutions = api.request('GET', '/rest/api/3/resolution')
    resolved = copy.deepcopy(bindings)
    resolved.update(projects={}, issue_types={}, statuses=statuses, resolutions={})
    variables = {'project_lead_account_ids': {}, 'permission_scheme_ids': {}, 'project_template_keys': {},
                 'work_type_metadata': {}, 'work_type_remote_names': {}}
    imports = []; gaps = []; workflow_ops = []; deferred_permissions = []
    bootstrap_ops = []; role_ids = {}; profile_ids = {}
    if bindings.get('permission_schemes'):
        role_ids, profile_ids, bootstrap_ops, permission_gaps = permission_operations(docs, selected, bindings, api, myself['accountId'])
        gaps.extend(permission_gaps)
        resolved['project_roles'] = {name: {**bindings['project_roles'][name], 'id': value} for name, value in role_ids.items()}
        resolved['permission_schemes'] = {name: {**bindings['permission_schemes'][name], 'id': value} for name, value in profile_ids.items()}
    templates = {'kanban': 'com.pyxis.greenhopper.jira:gh-simplified-kanban-classic',
                 'scrum': 'com.pyxis.greenhopper.jira:gh-simplified-scrum-classic',
                 'it-service-management': 'com.atlassian.servicedesk:simplified-it-service-management'}
    for p in selected['projects']['projects']:
        key = p['key']
        if p['project_type'] not in available_types: gaps.append(f'{key}: product entitlement is unavailable')
        existing = one([x for x in projects if x['key'] == key], 'project ' + key)
        if existing:
            if existing.get('style') != 'classic' or existing['projectTypeKey'] != p['project_type']:
                gaps.append(f'{key}: existing project type/management requires migration')
            resolved['projects'][key] = str(existing['id'])
            imports.append({'to': f'jira_project.projects[{json.dumps(key)}]', 'id': str(existing['id'])})
        existing_lead = api.request('GET', '/rest/api/3/project/' + str(existing['id'])).get('lead', {}).get('accountId') if existing else None
        lead = settings.get('project_lead_account_ids', {}).get(key, existing_lead or myself['accountId'])
        if lead != myself['accountId'] and not api.request('GET', '/rest/api/3/user', query={'accountId': lead}).get('active'):
            gaps.append(f'{key}: selected lead is inactive')
        variables['project_lead_account_ids'][key] = lead
        variables['project_template_keys'][key] = settings.get('project_template_keys', {}).get(key, templates[p['template']])
        scheme_id = settings.get('permission_scheme_ids', {}).get(key)
        if bindings.get('permission_schemes'):
            if scheme_id is not None: gaps.append(f'{key}: use either permission profiles or explicit scheme IDs')
            variables['permission_scheme_ids'][key] = profile_ids.get(p['permission_profile'])
        elif scheme_id is None:
            gaps.append(f'{key}: bind permission_scheme_ids explicitly for permission profile {p["permission_profile"]}')
        elif str(scheme_id) not in {str(s['id']) for s in native_schemes}:
            gaps.append(f'{key}: selected permission scheme does not exist')
        else: variables['permission_scheme_ids'][key] = scheme_id
        if settings.get('defer_permission_assignment', False):
            target_id = variables['permission_scheme_ids'][key]
            observed_permission = api.request('GET', '/rest/api/3/project/' + str(existing['id']) + '/permissionscheme') if existing else None
            variables['permission_scheme_ids'][key] = int(observed_permission['id']) if observed_permission else None
            deferred_permissions.append({'project': key, 'permission_profile': p['permission_profile'],
                'desired_scheme_id': target_id, 'observed_scheme_id': variables['permission_scheme_ids'][key],
                'status': 'deferred', 'reason': 'Explicit deployment option preserves Jira default permissions.'})
    for name in sorted({n for p in selected['projects']['projects'] for n in p['work_types']}):
        native = find_type(name, types, settings.get('work_type_names', {}).get(name))
        explicit = settings.get('work_type_metadata', {}).get(name)
        if native:
            resolved['issue_types'][name] = {'id': str(native['id']), 'is_subtask': native['subtask']}
            variables['work_type_remote_names'][name] = native['name']
            variables['work_type_metadata'][name] = explicit or {'description': native.get('description', ''), 'is_subtask': native['subtask']}
            if explicit and explicit['is_subtask'] != native['subtask']:
                gaps.append(f'{name}: subtask metadata conflicts with the existing type')
            imports.append({'to': f'jira_issue_type.work_types[{json.dumps(name)}]', 'id': str(native['id'])})
        elif explicit:
            variables['work_type_metadata'][name] = explicit
            variables['work_type_remote_names'][name] = settings.get('work_type_names', {}).get(name, name)
        else: gaps.append(f'{name}: supply work_type_metadata for this missing type')
    terminal = {t['to'] for w in selected['workflow-definitions']['workflow_definitions'].values() for t in w['transitions'] if 'set_resolution' in t['effects']}
    for name in terminal:
        explicit = bindings.get('resolutions', {}).get(name)
        candidates = [r for r in resolutions if str(r['id']) == str(explicit)] if explicit else [r for r in resolutions if r['name'] == 'Done']
        chosen = one(candidates, 'resolution ' + name)
        if chosen: resolved['resolutions'][name] = str(chosen['id'])
        else: gaps.append(f'{name}: bind an existing resolution ID')
    for name, definition in selected['workflow-definitions']['workflow_definitions'].items():
        binding = bindings.get('workflows', {}).get(name, {})
        try: workflow_ops.append(workflow_operation(api, definition, binding, statuses, resolved['resolutions'], validate_remote))
        except (DeploymentError, MappingError) as exc: gaps.append(f'{name}: {exc}')
    scheme_ops = []
    scheme_inventories = {
        'work_type_schemes': pages(api, '/rest/api/3/issuetypescheme', {'expand': 'issueTypes'}),
        'workflow_schemes': pages(api, '/rest/api/3/workflowscheme')}
    for name, definition in selected['workflow-definitions']['workflow_schemes'].items():
        for kind in ('work_type_schemes', 'workflow_schemes'):
            binding = bindings.get(kind, {}).get(name, {})
            if not binding.get('name'):
                gaps.append(f'{name}: supply the native {kind} name')
                continue
            existing = one([s for s in scheme_inventories[kind] if s['name'] == binding['name']], 'scheme ' + binding['name'])
            if binding.get('id') and (not existing or str(existing['id']) != str(binding['id'])):
                gaps.append(f'{name}: supplied {kind} ID/name does not match current Jira inventory')
            members = next(p['work_types'] for p in selected['projects']['projects'] if p['work_type_scheme'] == name)
            if existing:
                needed_types = members if kind == 'work_type_schemes' else definition['overrides']
                if any(n not in resolved['issue_types'] for n in needed_types):
                    gaps.append(f'{name}: existing scheme needs reconciliation for missing work types')
                else:
                    try:
                        clean_binding = {k: v for k, v in binding.items() if k != 'id'}
                        if kind == 'work_type_schemes':
                            expected = work_type_scheme_request(members, clean_binding, resolved['issue_types'])['body']
                            matched = scheme_members(api, existing['id']) == expected['issueTypeIds'] and str(existing.get('defaultIssueTypeId')) == expected['defaultIssueTypeId']
                        else:
                            expected = workflow_scheme_request(definition, clean_binding, resolved['issue_types'], resolved['workflows'])['body']
                            matched = existing.get('defaultWorkflow') == expected['defaultWorkflow'] and existing.get('issueTypeMappings', {}) == expected['issueTypeMappings']
                        if not matched: gaps.append(f'{name}: existing {kind} differs; reconciliation adapter required')
                    except MappingError as exc: gaps.append(f'{name}: {exc}')
                resolved[kind][name] = {**binding, 'id': str(existing['id'])}
            scheme_ops.append({'kind': kind, 'name': binding['name'], 'action': 'reuse' if existing else 'create', 'id': str(existing['id']) if existing else None})
        default = bindings.get('work_type_schemes', {}).get(name, {}).get('default_work_type')
        members = next(p['work_types'] for p in selected['projects']['projects'] if p['work_type_scheme'] == name)
        if default not in members: gaps.append(f'{name}: bind default_work_type to a scheme member')
        elif default in variables['work_type_metadata'] and variables['work_type_metadata'][default]['is_subtask']:
            gaps.append(f'{name}: default work type cannot be a subtask')
    account_tasks = [{'account': name, 'task': 'Create or identify the native service account in Atlassian Administration; record its account ID and generated email.',
                      'status': 'human_task', 'phase': 'agent_setup', 'blocks_provisioning': False,
                      'projects': sorted({p for role, ps in account['project_access'].items() if role != 'denied' for p in ps} & {p['key'] for p in selected['projects']['projects']})}
                     for name, account in docs['service-account-registry']['service_account_registry'].items()
                     if account['account_id'] is None and any(p in {x['key'] for x in selected['projects']['projects']} for role, ps in account['project_access'].items() if role != 'denied' for p in ps)]
    return selected, resolved, variables, imports, {'source_digest': source_digest(docs, bindings),
        'site': docs['site']['site']['base_url'], 'project_keys': sorted(p['key'] for p in selected['projects']['projects']),
        'scope': 'project_configuration', 'ready': not gaps, 'required_inputs': gaps, 'workflow_operations': workflow_ops,
        'scheme_operations': scheme_ops,
        'bootstrap_operations': bootstrap_ops, 'bootstrap_account_id': myself['accountId'],
        'human_tasks': account_tasks, 'account_access_applied': False,
        'deferred_permission_assignments': deferred_permissions,
        'permission_model': 'declared role grants with privileged bootstrap access' if bootstrap_ops else 'explicit existing permission scheme bindings',
        'rest_after_terraform': 'Resolve work-type/project IDs, create or reuse schemes, associate and verify.'}


def scheme_members(api, scheme_id):
    members = pages(api, '/rest/api/3/issuetypescheme/mapping', {'issueTypeSchemeId': scheme_id})
    return [str(m['issueTypeId']) for m in members]


def permission_payload(contract, profile, binding, role_ids, account_id):
    definition = contract['permission_profiles'][profile]
    grants = [{'permission': p, 'holder': {'type': 'user', 'parameter': account_id}}
              for p in sorted(set(contract['bootstrap_permissions'] + definition['bootstrap_extra_permissions']))]
    for role, permissions in definition['roles'].items():
        if role_ids.get(role) is None: raise DeploymentError('project role ID is not resolved: ' + role)
        grants.extend({'permission': p, 'holder': {'type': 'projectRole', 'parameter': str(role_ids[role])}} for p in permissions)
    return {'name': binding['name'], 'description': definition['description'], 'permissions': grants}


def permission_signature(grants, platform_role_ids=()):
    """Compare declared grants; Jira manages its reserved app-access role itself."""
    return sorted((g['permission'], g['holder']['type'], str(g['holder'].get('value', g['holder'].get('parameter', ''))))
                  for g in grants if not (g['holder']['type'] == 'projectRole'
                    and str(g['holder'].get('value', g['holder'].get('parameter', ''))) in platform_role_ids))


def permission_operations(docs, selected, bindings, api, account_id):
    contract = docs.get('permission-profiles')
    if not contract: raise DeploymentError('permission-profile definitions are required for scheme creation')
    profiles = {p['permission_profile'] for p in selected['projects']['projects']}
    roles = {r for p in profiles for r in contract['permission_profiles'][p]['roles']}
    inventory = [r for r in api.request('GET', '/rest/api/3/role') if r.get('scope', {}).get('type', 'GLOBAL') == 'GLOBAL']
    platform_role_ids = sorted(str(r['id']) for r in inventory if r['name'] == 'atlassian-addons-project-access')
    available = api.request('GET', '/rest/api/3/permissions')['permissions']
    schemes = api.request('GET', '/rest/api/3/permissionscheme')['permissionSchemes']
    role_ids = {}; scheme_ids = {}; operations = []; gaps = []
    for role in sorted(roles):
        binding = bindings.get('project_roles', {}).get(role, {})
        if not binding.get('name'):
            gaps.append(role + ': supply the native project role name'); continue
        existing = one([r for r in inventory if r['name'] == binding['name']], 'project role ' + binding['name'])
        if binding.get('id') and (not existing or str(existing['id']) != binding['id']):
            gaps.append(role + ': supplied project role ID/name does not match')
        if existing and api.request('GET', '/rest/api/3/role/' + str(existing['id'])).get('actors'):
            gaps.append(role + ': managed project role has default actors; explicit membership is required')
        role_ids[role] = str(existing['id']) if existing else None
        operations.append({'kind': 'project_role', 'key': role, 'name': binding['name'], 'action': 'reuse' if existing else 'create', 'id': role_ids[role]})
    for profile in sorted(profiles):
        binding = bindings.get('permission_schemes', {}).get(profile, {})
        if not binding.get('name'):
            gaps.append(profile + ': supply the native permission scheme name'); continue
        definition = contract['permission_profiles'][profile]
        permissions = set(contract['bootstrap_permissions'] + definition['bootstrap_extra_permissions']) | {p for ps in definition['roles'].values() for p in ps}
        if any(available.get(p, {}).get('type') != 'PROJECT' for p in permissions):
            gaps.append(profile + ': permission definitions must reference supported project permissions')
        existing = one([s for s in schemes if s['name'] == binding['name']], 'permission scheme ' + binding['name'])
        if binding.get('id') and (not existing or str(existing['id']) != binding['id']):
            gaps.append(profile + ': supplied permission scheme ID/name does not match')
        if existing:
            try:
                expected = permission_payload(contract, profile, binding, role_ids, account_id)
                observed = api.request('GET', '/rest/api/3/permissionscheme/' + str(existing['id']) + '/permission')['permissions']
                if permission_signature(observed, platform_role_ids) != permission_signature(expected['permissions']):
                    gaps.append(profile + ': existing permission grants differ; explicit reconciliation is required')
            except DeploymentError as exc: gaps.append(str(exc))
        scheme_ids[profile] = int(existing['id']) if existing else None
        operations.append({'kind': 'permission_scheme', 'key': profile, 'name': binding['name'], 'action': 'reuse' if existing else 'create',
                           'id': scheme_ids[profile], 'platform_managed_role_ids': platform_role_ids})
    return role_ids, scheme_ids, operations, gaps


def run_bootstrap(docs, bindings, api, record, verify=False, prepared=None):
    selected, resolved, variables, _, plan = prepared or resolve(docs, bindings, api)
    if plan['required_inputs']: raise DeploymentError('; '.join(plan['required_inputs']))
    if not bindings.get('permission_schemes'): return {'status': 'existing_permission_bindings_reused'}
    role_ids = {name: item['id'] for name, item in resolved['project_roles'].items()}
    operations = plan['bootstrap_operations']
    contract = docs['permission-profiles']
    for operation in operations:
        key = operation['key']; item_id = operation['id']
        if operation['kind'] == 'project_role':
            if item_id is None:
                created = api.request('POST', '/rest/api/3/role', {'name': operation['name'], 'description': contract['project_roles'][key]['description']})
                item_id = str(created['id']); role_ids[key] = item_id
            resolved['project_roles'][key]['id'] = str(item_id)
            record({**operation, 'id': item_id, 'confirmation': 'api_success' if operation['action'] == 'create' else 'discovery'})
            if not verify: continue
            observed = api.request('GET', '/rest/api/3/role/' + str(item_id))
            if observed['name'] != operation['name'] or observed.get('actors'):
                raise DeploymentError('project role readback verification failed')
        else:
            payload = permission_payload(contract, key, bindings['permission_schemes'][key], role_ids, plan['bootstrap_account_id'])
            if item_id is None:
                created = api.request('POST', '/rest/api/3/permissionscheme', payload)
                item_id = int(created['id'])
            resolved['permission_schemes'][key]['id'] = str(item_id)
            if not verify:
                record({**operation, 'id': item_id, 'confirmation': 'api_success' if operation['action'] == 'create' else 'discovery'})
                continue
            try:
                observed = api.request('GET', '/rest/api/3/permissionscheme/' + str(item_id) + '/permission')['permissions']
            except DeploymentError:
                record({**operation, 'id': item_id, 'verified': False})
                raise
            platform_ids = operation['platform_managed_role_ids']
            platform_count = sum(g['holder']['type'] == 'projectRole' and str(g['holder'].get('value', g['holder'].get('parameter', ''))) in platform_ids for g in observed)
            record({**operation, 'id': item_id, 'platform_managed_grant_count': platform_count})
            if permission_signature(observed, platform_ids) != permission_signature(payload['permissions']):
                raise DeploymentError('permission scheme grant readback verification failed')
    for project in selected['projects']['projects']:
        if not bindings.get('deployment', {}).get('defer_permission_assignment', False):
            variables['permission_scheme_ids'][project['key']] = int(resolved['permission_schemes'][project['permission_profile']]['id'])
    for deferred in plan['deferred_permission_assignments']:
        deferred['desired_scheme_id'] = int(resolved['permission_schemes'][deferred['permission_profile']]['id'])
    return {'status': 'bootstrap_configuration_verified' if verify else 'bootstrap_operations_completed', 'remote_comparison_performed': verify}


def run_rest(docs, bindings, api, record, verify=False, prepared=None, compare_only=False):
    verify = verify or compare_only
    selected, resolved, variables, _, plan = prepared or resolve(docs, bindings, api)
    if plan['required_inputs']: raise DeploymentError('; '.join(plan['required_inputs']))
    if any(n not in resolved['issue_types'] for p in selected['projects']['projects'] for n in p['work_types']):
        raise DeploymentError('Terraform has not created all required work types')
    if any(p['key'] not in resolved['projects'] for p in selected['projects']['projects']):
        raise DeploymentError('Terraform has not created all selected projects')
    deferred = bindings.get('deployment', {}).get('defer_permission_assignment', False)
    if not deferred and any(sid is None for sid in variables['permission_scheme_ids'].values()):
        raise DeploymentError('bootstrap has not created all required permission schemes')
    for operation in plan['workflow_operations']:
        name = next(n for n, b in bindings['workflows'].items() if b['name'] == operation['name'])
        if operation['action'] != 'reuse':
            if compare_only: raise DeploymentError(operation['name'] + ': workflow differs from declaration')
            request = copy.deepcopy(operation['request'])
            # Earlier calls may have created shared statuses; use returned IDs, without rediscovery.
            for status in request['body']['statuses']:
                if status['name'] in resolved['statuses']:
                    status['id'] = resolved['statuses'][status['name']]['id']
            response = api.request(request['method'], request['path'], request['body'])
            record({'resource': 'workflow:' + operation['name'], 'action': operation['action'], 'confirmation': 'api_success'})
            if response and response.get('statuses'):
                resolved['statuses'].update(status_bindings(response['statuses']))
            elif any('id' not in s for s in request['body']['statuses']):
                # IDs are execution dependencies, not a readback confirmation.
                resolved['statuses'].update(status_bindings(pages(api, '/rest/api/3/statuses/search')))
            if verify:
                check = workflow_operation(api, selected['workflow-definitions']['workflow_definitions'][name], bindings['workflows'][name], resolved['statuses'], resolved['resolutions'])
                if check['action'] != 'reuse': raise DeploymentError('workflow readback does not match the declaration')
        else:
            record({'resource': 'workflow:' + operation['name'], 'action': 'reuse', 'confirmation': 'discovery'})
    for name, definition in selected['workflow-definitions']['workflow_schemes'].items():
        members = next(p['work_types'] for p in selected['projects']['projects'] if p['work_type_scheme'] == name)
        for kind, build in (
            ('work_type_schemes', lambda b: work_type_scheme_request(members, b, resolved['issue_types'])),
            ('workflow_schemes', lambda b: workflow_scheme_request(definition, b, resolved['issue_types'], resolved['workflows']))):
            binding = {k: v for k, v in bindings[kind][name].items() if k != 'id'}
            request = build(binding)
            existing = resolved[kind].get(name) if resolved[kind].get(name, {}).get('id') else None
            if existing:
                item = existing; action = 'reuse'
            else:
                if compare_only: raise DeploymentError(binding['name'] + ': scheme is missing')
                item = api.request(request['method'], request['path'], request['body']); action = 'create'
                if kind == 'work_type_schemes' and item:
                    item = {'id': item.get('issueTypeSchemeId')}
            if not item or item.get('id') is None: raise DeploymentError('scheme creation/readback did not return an ID')
            resolved[kind][name] = {**binding, 'id': str(item['id'])}
            record({'resource': kind + ':' + name, 'action': action, 'id': str(item['id']),
                    'confirmation': 'api_success' if action == 'create' else 'discovery'})
            if not verify or action == 'reuse': continue
            endpoint = '/rest/api/3/issuetypescheme' if kind == 'work_type_schemes' else '/rest/api/3/workflowscheme'
            observed = one([s for s in pages(api, endpoint) if str(s['id']) == str(item['id'])], 'created scheme ' + binding['name'])
            if not observed or observed['name'] != binding['name']:
                raise DeploymentError('scheme creation/readback verification failed')
            if kind == 'work_type_schemes':
                matches = (scheme_members(api, item['id']) == request['body']['issueTypeIds']
                           and str(observed.get('defaultIssueTypeId')) == request['body']['defaultIssueTypeId'])
            else:
                matches = (observed.get('defaultWorkflow') == request['body']['defaultWorkflow']
                           and observed.get('issueTypeMappings', {}) == request['body']['issueTypeMappings'])
            if not matches: raise DeploymentError('scheme configuration readback verification failed')
    for project in selected['projects']['projects']:
        key = project['key']; pid = resolved['projects'][key]
        empty_checked = False
        for kind, lookup, endpoint, nested in (
            ('work_type', 'work_type_schemes', '/rest/api/3/issuetypescheme/project', 'issueTypeScheme'),
            ('workflow', 'workflow_schemes', '/rest/api/3/workflowscheme/project', 'workflowScheme')):
            sid = resolved[lookup][project['work_type_scheme']]['id']
            existing = api.request('GET', endpoint, query={'projectId': pid}).get('values', [])
            matches = any(str(row.get(nested, {}).get('id')) == sid and pid in [str(p) for p in row.get('projectIds', [])] for row in existing)
            if not matches:
                if compare_only: raise DeploymentError(f'{key}: {kind} scheme association differs')
                if not empty_checked and api.request('GET', '/rest/api/3/search/jql', query={'jql': f'project = "{key}"', 'maxResults': 1, 'fields': 'id'}).get('issues'):
                    raise DeploymentError(f'{key}: scheme changes on populated projects require migration')
                empty_checked = True
                request = scheme_association(kind, pid, sid)
                api.request(request['method'], request['path'], request['body'])
            if verify and not matches:
                readback = api.request('GET', endpoint, query={'projectId': pid}).get('values', [])
                if not any(str(row.get(nested, {}).get('id')) == sid and pid in [str(p) for p in row.get('projectIds', [])] for row in readback):
                    raise DeploymentError(f'{key}: scheme association verification failed')
            record({'resource': kind + '-association:' + key, 'action': 'reuse' if matches else 'associate',
                    'verified': verify, 'confirmation': 'discovery' if matches else 'api_success'})
        if not verify:
            if deferred: record({'resource': 'permission-assignment:' + key, 'action': 'deferred'})
            continue
        observed = api.request('GET', '/rest/api/3/project/' + pid)
        permission = api.request('GET', '/rest/api/3/project/' + pid + '/permissionscheme')
        if observed['name'] != project['name'] or observed['projectTypeKey'] != project['project_type'] or observed.get('style') != 'classic' or str(permission['id']) != str(variables['permission_scheme_ids'][key]):
            raise DeploymentError(f'{key}: project configuration verification failed')
        if deferred:
            record({'resource': 'permission-assignment:' + key, 'action': 'deferred',
                    'observed_scheme_id': str(permission['id']), 'observed_scheme_name': permission.get('name')})
        if bindings.get('permission_schemes') and not deferred:
            for role in docs['permission-profiles']['permission_profiles'][project['permission_profile']]['roles']:
                rid = resolved['project_roles'][role]['id']
                role_state = api.request('GET', '/rest/api/3/project/' + pid + '/role/' + str(rid))
                if str(role_state['id']) != str(rid) or role_state['name'] != bindings['project_roles'][role]['name']:
                    raise DeploymentError(f'{key}: project role verification failed')
    status = ('project_structure_verified_permissions_deferred' if deferred else 'project_configuration_verified') if verify else ('project_operations_completed_permissions_deferred' if deferred else 'project_operations_completed')
    return {'status': status, 'remote_comparison_performed': verify,
            'projects': resolved['projects'], 'resolved_bindings': resolved,
            'deferred_permission_assignments': plan['deferred_permission_assignments'],
            'human_tasks': plan['human_tasks'], 'account_access_applied': False, 'runtime_role_memberships_managed': False,
            'issue_transition_behavior_tested': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'prepare-apply', 'bootstrap', 'rest', 'verify'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--bindings', type=Path, required=True)
    args = parser.parse_args()
    docs, errors = validate(args.root)
    if errors: raise DeploymentError('; '.join(errors))
    bindings, _ = load(args.bindings, args.bindings.parent)
    schema = json.loads((Path(__file__).parent / 'bindings.schema.json').read_text())
    errors = list(Draft202012Validator(schema).iter_errors(bindings))
    if errors: raise DeploymentError('invalid execution bindings: ' + '; '.join(e.json_path for e in errors))
    api = Jira()
    work = args.workdir
    if not work.is_dir(): raise DeploymentError('a private deployment work directory is required')
    if args.command in {'prepare', 'prepare-apply'}:
        previous_path = work / 'deployment-plan.json'
        if previous_path.exists():
            previous = json.loads(previous_path.read_text())
            desired_keys = sorted(p['key'] for p in select(docs, bindings.get('deployment', {}).get('project_keys'))['projects']['projects'])
            if previous.get('site', docs['site']['site']['base_url']) != docs['site']['site']['base_url'] or previous.get('project_keys', desired_keys) != desired_keys:
                raise DeploymentError('work directory belongs to another site/project selection; use a separate directory')
        selected, resolved, variables, imports, plan = resolve(docs, bindings, api)
        write(work / 'deployment-plan.json', plan)
        write(work / 'resolved-bindings.json', resolved)
        if plan['required_inputs']:
            print(json.dumps({'ready': False, 'required_inputs': plan['required_inputs'], 'human_tasks': plan['human_tasks']}, indent=2)); return 2
        if args.command == 'prepare-apply':
            journal = []
            def record_bootstrap(event):
                journal.append(event); write(work / 'bootstrap-journal.json', journal)
            try:
                result = run_bootstrap(docs, bindings, api, record_bootstrap, prepared=(selected, resolved, variables, imports, plan))
            except (DeploymentError, MappingError) as exc:
                write(work / 'deployment-result.json', {'status': 'failed', 'reason': str(exc), 'completed_operations': journal})
                raise
            write(work / 'bootstrap-result.json', result)
            write(work / 'deployment-plan.json', plan)
            write(work / 'resolved-bindings.json', resolved)
        write(work / 'execution-inputs.json', {'mapper_digest': mapper_digest(), 'api_version': 3,
              'resolved': resolved, 'variables': variables, 'imports': imports})
        tfdir = work / 'terraform'; tfdir.mkdir(exist_ok=True, mode=0o700)
        write(tfdir / 'projects.tf.json', terraform_configuration(selected, bindings.get('deployment', {}).get('defer_permission_assignment', False)))
        write(tfdir / 'deployment.auto.tfvars.json', variables)
        write(tfdir / 'imports.tf.json', {'import': imports})
        print(json.dumps({'ready': True, 'projects': [p['key'] for p in selected['projects']['projects']], 'human_tasks': plan['human_tasks']})); return 0
    prepared = json.loads((work / 'deployment-plan.json').read_text()) if args.command != 'verify' else None
    if args.command != 'verify' and (not prepared['ready'] or prepared['source_digest'] != source_digest(docs, bindings)):
        raise DeploymentError('declarations or bindings changed after Terraform preparation')
    journal = []
    def record(event):
        journal.append(event); write(work / ('bootstrap-journal.json' if args.command == 'bootstrap' else 'verification-journal.json' if args.command == 'verify' else 'rest-journal.json'), journal)
    try:
        if args.command == 'verify':
            result = run_rest(docs, bindings, api, record, compare_only=True)
        elif args.command == 'bootstrap':
            result = run_bootstrap(docs, bindings, api, record)
        else:
            inputs = json.loads((work / 'execution-inputs.json').read_text())
            if inputs['mapper_digest'] != mapper_digest() or inputs['api_version'] != 3:
                raise DeploymentError('mapping implementation changed after preparation; prepare again')
            selected = select(docs, bindings.get('deployment', {}).get('project_keys'))
            state = json.loads((work / 'terraform/terraform.tfstate').read_text())
            context = terraform_bindings((selected, inputs['resolved'], inputs['variables'], inputs['imports'], prepared), state)
            result = run_rest(docs, bindings, api, record, prepared=context)
    except (DeploymentError, MappingError) as exc:
        write(work / ('verification-result.json' if args.command == 'verify' else 'deployment-result.json'), {'status': 'failed', 'reason': str(exc), 'completed_operations': journal})
        raise
    write(work / ('bootstrap-result.json' if args.command == 'bootstrap' else 'verification-result.json' if args.command == 'verify' else 'deployment-result.json'), result)
    print(json.dumps({k: v for k, v in result.items() if k != 'resolved_bindings'}, indent=2)); return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (DeploymentError, MappingError) as exc:
        print(json.dumps({'error': 'deployment_input_or_operation_failed', 'reason': str(exc)})); raise SystemExit(2)
