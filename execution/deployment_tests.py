import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from adapters import workflow_request
from deployment import DeploymentError, Jira, find_type, pages, resolve, run_bootstrap as apply_bootstrap, run_rest as apply_rest, semantic_workflow, workflow_operation, terraform_bindings
from bindings import generate
from runner import validate, terraform_configuration


# Retain the earlier readback regression tests through explicit comparison mode.
def run_bootstrap(*args, **kwargs):
    return apply_bootstrap(*args, verify=True, **kwargs)


def run_rest(*args, **kwargs):
    return apply_rest(*args, verify=True, **kwargs)


def bindings():
    return {'deployment': {'project_keys': ['PLAT'], 'permission_scheme_ids': {'PLAT': 17},
                          'work_type_metadata': {n: {'description': n + ' work', 'is_subtask': False} for n in ('Bug', 'Spike')}},
            'workflows': {'delivery': {'name': 'declared-delivery'}},
            'work_type_schemes': {'engineering': {'name': 'declared-types', 'default_work_type': 'Task'}},
            'workflow_schemes': {'engineering': {'name': 'declared-workflows'}}}


class FakeJira:
    def __init__(self, docs):
        self.docs = docs; self.calls = []; self.projects = []; self.workflows = []
        self.types = [{'id': str(i + 1), 'name': n, 'description': n + ' native', 'subtask': n == 'Sub-task'}
                      for i, n in enumerate(('Epic', 'Story', 'Task', 'Sub-task'))]
        self.statuses = [{'id': str(i + 10), 'statusReference': str(i + 10), 'name': n, 'statusCategory': c, 'scope': {'type': 'GLOBAL'}}
                         for i, (n, c) in enumerate(docs['workflow-definitions']['workflow_definitions']['delivery']['statuses'].items())]
        self.schemes = {'work_type': [], 'workflow': []}; self.associations = {'work_type': {}, 'workflow': {}}
        self.populated = False; self.deny_validation = False; self.inject_bad_readback = False
        self.inject_bad_scheme = False
        self.roles = []; self.permission_schemes = []; self.project_permissions = {}
        self.runtime_actors = []
        self.inject_platform_grants = False

    def add_terraform_resources(self):
        self.projects.append({'id': '100', 'key': 'PLAT', 'name': 'Platform Engineering', 'projectTypeKey': 'software', 'style': 'classic'})
        self.types.extend({'id': str(i + 200), 'name': n, 'description': n + ' work', 'subtask': False} for i, n in enumerate(('Bug', 'Spike')))

    def request(self, method, path, body=None, query=None):
        query = query or {}; self.calls.append((method, path, copy.deepcopy(body), copy.deepcopy(query)))
        if method == 'GET':
            simple = {
                '/rest/api/3/serverInfo': {'baseUrl': self.docs['site']['site']['base_url']},
                '/rest/api/3/myself': {'accountId': 'human-admin', 'active': True},
                '/rest/api/3/mypermissions': {'permissions': {'ADMINISTER': {'havePermission': True}}},
                '/rest/api/3/project/type/accessible': [{'key': 'software'}, {'key': 'service_desk'}],
                '/rest/api/3/issuetype': self.types,
                '/rest/api/3/permissionscheme': {'permissionSchemes': [{'id': 17, 'name': 'Explicit scheme'}]},
                '/rest/api/3/role': self.roles,
                '/rest/api/3/permissions': {'permissions': {p: {'type': 'PROJECT'} for p in self.permission_keys()}},
                '/rest/api/3/resolution': [{'id': '7', 'name': 'Done'}],
                '/rest/api/3/project/100': self.projects[0] if self.projects else {},
                '/rest/api/3/project/100/permissionscheme': {'id': 17},
                '/rest/api/3/search/jql': {'issues': [{'id': '1'}] if self.populated else []},
            }
            simple['/rest/api/3/permissionscheme']['permissionSchemes'].extend(self.permission_schemes)
            for project in self.projects:
                simple['/rest/api/3/project/' + project['id']] = project
                simple['/rest/api/3/project/' + project['id'] + '/permissionscheme'] = {'id': self.project_permissions.get(project['key'], 17)}
            if path in simple: return copy.deepcopy(simple[path])
            if path.startswith('/rest/api/3/role/'):
                return copy.deepcopy(next(r for r in self.roles if str(r['id']) == path.split('/')[-1]))
            if path.startswith('/rest/api/3/permissionscheme/') and path.endswith('/permission'):
                return {'permissions': copy.deepcopy(next(s['permissions'] for s in self.permission_schemes if str(s['id']) == path.split('/')[-2]))}
            if '/role/' in path and path.startswith('/rest/api/3/project/'):
                role = next(r for r in self.roles if str(r['id']) == path.split('/')[-1])
                return {'id': role['id'], 'name': role['name'], 'actors': copy.deepcopy(self.runtime_actors)}
            if path in ('/rest/api/3/project/search', '/rest/api/3/statuses/search', '/rest/api/3/workflows/search', '/rest/api/3/issuetypescheme', '/rest/api/3/workflowscheme'):
                values = {'/rest/api/3/project/search': self.projects, '/rest/api/3/statuses/search': self.statuses,
                          '/rest/api/3/workflows/search': self.workflows, '/rest/api/3/issuetypescheme': self.schemes['work_type'],
                          '/rest/api/3/workflowscheme': self.schemes['workflow']}[path]
                return {'values': copy.deepcopy(values), 'isLast': True}
            if path == '/rest/api/3/issuetypescheme/mapping':
                scheme = next(s for s in self.schemes['work_type'] if str(s['id']) == str(query['issueTypeSchemeId']))
                return {'values': [{'issueTypeId': n} for n in scheme['issueTypeIds']], 'isLast': True}
            if path in ('/rest/api/3/issuetypescheme/project', '/rest/api/3/workflowscheme/project'):
                kind = 'work_type' if 'issuetype' in path else 'workflow'
                nested = 'issueTypeScheme' if kind == 'work_type' else 'workflowScheme'
                sid = self.associations[kind].get(str(query['projectId']))
                if self.inject_bad_readback: sid = None
                return {'values': [{nested: {'id': sid}, 'projectIds': [str(query['projectId'])]}] if sid else []}
        if method == 'POST':
            if path == '/rest/api/3/workflows':
                return {'workflows': [copy.deepcopy(w) for w in self.workflows if w['id'] in body['workflowIds']], 'statuses': copy.deepcopy(self.statuses)}
            if path.endswith('/validation'):
                return {'errors': [{'message': 'invalid'}] if self.deny_validation else []}
            if path in ('/rest/api/3/workflows/create', '/rest/api/3/workflows/update'):
                workflow = copy.deepcopy(body['workflows'][0]); workflow['id'] = workflow.get('id', 'workflow-' + str(len(self.workflows) + 1)); workflow['version'] = {'id': 'version-1', 'versionNumber': 1}
                for s in body['statuses']:
                    if 'id' not in s:
                        s['id'] = str(len(self.statuses) + 10)
                        self.statuses.append({**copy.deepcopy(s), 'statusReference': s['id'], 'scope': {'type': 'GLOBAL'}})
                refs = {s['statusReference']: str(s['id']) for s in body['statuses']}
                for s in workflow['statuses']: s['statusReference'] = refs[s['statusReference']]
                for t in workflow['transitions']:
                    t['toStatusReference'] = refs[t['toStatusReference']]
                    for link in t['links']: link['fromStatusReference'] = refs[link['fromStatusReference']]
                if path.endswith('/update'):
                    workflow['name'] = next(w['name'] for w in self.workflows if w['id'] == workflow['id'])
                    self.workflows = [w for w in self.workflows if w['id'] != workflow['id']]
                self.workflows.append(workflow)
                return {'workflows': [copy.deepcopy(workflow)], 'statuses': copy.deepcopy(self.statuses)}
            if path in ('/rest/api/3/issuetypescheme', '/rest/api/3/workflowscheme'):
                kind = 'work_type' if 'issuetype' in path else 'workflow'
                scheme = {**copy.deepcopy(body), 'id': str((300 if kind == 'work_type' else 400) + len(self.schemes[kind]))}
                self.schemes[kind].append(scheme)
                if self.inject_bad_scheme and kind == 'work_type': scheme['defaultIssueTypeId'] = 'wrong'
                return {'issueTypeSchemeId': scheme['id']} if kind == 'work_type' else copy.deepcopy(scheme)
            if path == '/rest/api/3/role':
                role = {**copy.deepcopy(body), 'id': 500 + len(self.roles), 'actors': []}
                self.roles.append(role); return copy.deepcopy(role)
            if path == '/rest/api/3/permissionscheme':
                scheme = {**copy.deepcopy(body), 'id': 600 + len(self.permission_schemes)}
                if self.inject_platform_grants:
                    scheme['permissions'].extend({'permission': p, 'holder': {'type': 'projectRole', 'value': '10003'}}
                                                 for p in ('ADMINISTER_PROJECTS', 'BROWSE_PROJECTS'))
                self.permission_schemes.append(scheme); return copy.deepcopy(scheme)
        if method == 'PUT' and path in ('/rest/api/3/issuetypescheme/project', '/rest/api/3/workflowscheme/project'):
            kind = 'work_type' if 'issuetype' in path else 'workflow'
            field = 'issueTypeSchemeId' if kind == 'work_type' else 'workflowSchemeId'
            self.associations[kind][body['projectId']] = body[field]; return None
        raise AssertionError(f'unexpected fake API call: {method} {path}')

    def permission_keys(self):
        contract = self.docs['permission-profiles']
        return set(contract['bootstrap_permissions']) | {p for d in contract['permission_profiles'].values() for p in [*d['bootstrap_extra_permissions'], *[p for ps in d['roles'].values() for p in ps]]}


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.docs, errors = validate(Path('/inputs')); self.assertEqual(errors, [])
        self.api = FakeJira(self.docs); self.bindings = bindings()

    def test_resolves_native_alias_and_existing_metadata_without_renaming(self):
        selected, resolved, variables, imports, plan = resolve(self.docs, self.bindings, self.api)
        self.assertTrue(plan['ready'], plan['required_inputs'])
        self.assertEqual([p['key'] for p in selected['projects']['projects']], ['PLAT'])
        self.assertEqual(variables['project_lead_account_ids']['PLAT'], 'human-admin')
        self.assertEqual(variables['work_type_remote_names']['Subtask'], 'Sub-task')
        self.assertTrue(resolved['issue_types']['Subtask']['is_subtask'])
        self.assertEqual(variables['work_type_metadata']['Task']['description'], 'Task native')
        self.assertEqual(len(imports), 4)
        self.assertEqual(plan['human_tasks'][0]['status'], 'human_task')
        self.assertFalse(plan['account_access_applied'])
        self.assertTrue(all(method != 'PUT' and not (method == 'POST' and path.endswith('/create')) for method, path, _, _ in self.api.calls))

    def test_required_permission_choice_is_reported_without_default_fallback(self):
        self.bindings['deployment']['permission_scheme_ids'] = {}
        _, _, _, _, plan = resolve(self.docs, self.bindings, self.api)
        self.assertFalse(plan['ready'])
        self.assertTrue(any('bind permission_scheme_ids explicitly' in item for item in plan['required_inputs']))

    def test_missing_new_type_metadata_is_reported(self):
        del self.bindings['deployment']['work_type_metadata']['Spike']
        self.assertIn('Spike: supply work_type_metadata for this missing type', resolve(self.docs, self.bindings, self.api)[4]['required_inputs'])

    def test_rejects_ambiguous_native_type(self):
        types = [{'name': 'Sub-task', 'subtask': True}, {'name': 'Sub task', 'subtask': True}]
        with self.assertRaises(DeploymentError): find_type('Subtask', types)
        self.assertEqual(find_type('Subtask', types, 'Sub-task')['name'], 'Sub-task')

    def test_project_type_mismatch_reported(self):
        self.api.add_terraform_resources(); self.api.projects[0]['style'] = 'next-gen'
        self.assertTrue(any('requires migration' in g for g in resolve(self.docs, self.bindings, self.api)[4]['required_inputs']))

    def test_mismatched_site_rejected(self):
        docs = copy.deepcopy(self.docs); docs['site']['site']['base_url'] = 'https://another.atlassian.net'
        with self.assertRaises(DeploymentError): resolve(docs, self.bindings, self.api)

    def test_rest_pipeline_and_second_run_reuses_everything(self):
        self.api.add_terraform_resources(); events = []
        result = run_rest(self.docs, self.bindings, self.api, events.append)
        self.assertEqual(result['status'], 'project_configuration_verified')
        self.assertFalse(result['account_access_applied'])
        self.assertEqual(len(events), 5)
        self.assertEqual(self.api.associations['workflow']['100'], '400')
        self.api.calls = []; repeated = []
        run_rest(self.docs, self.bindings, self.api, repeated.append)
        self.assertTrue(all(e['action'] == 'reuse' for e in repeated))
        self.assertFalse(any(method == 'PUT' or (method == 'POST' and path in ('/rest/api/3/workflows/create', '/rest/api/3/workflows/update', '/rest/api/3/issuetypescheme', '/rest/api/3/workflowscheme')) for method, path, _, _ in self.api.calls))

    def test_populated_project_blocks_scheme_changes(self):
        self.api.add_terraform_resources(); self.api.populated = True
        with self.assertRaisesRegex(DeploymentError, 'populated projects'):
            run_rest(self.docs, self.bindings, self.api, lambda event: None)
        self.assertFalse(any(method == 'PUT' for method, _, _, _ in self.api.calls))

    def test_failed_readback_is_failure(self):
        self.api.add_terraform_resources(); self.api.inject_bad_readback = True
        with self.assertRaisesRegex(DeploymentError, 'verification failed'):
            run_rest(self.docs, self.bindings, self.api, lambda event: None)

    def test_created_scheme_mismatch_blocks_association_and_records_id(self):
        self.api.add_terraform_resources(); self.api.inject_bad_scheme = True; events = []
        with self.assertRaisesRegex(DeploymentError, 'scheme configuration readback verification failed'):
            run_rest(self.docs, self.bindings, self.api, events.append)
        self.assertEqual(events[-1]['id'], '300')
        self.assertFalse(any(method == 'PUT' for method, _, _, _ in self.api.calls))

    def test_jira_workflow_validation_failure_blocks_preparation(self):
        self.api.deny_validation = True
        self.assertTrue(any('validation failed' in g for g in resolve(self.docs, self.bindings, self.api, validate_remote=True)[4]['required_inputs']))

    def test_existing_scheme_drift_does_not_recreate_duplicate(self):
        self.api.add_terraform_resources()
        self.api.schemes['work_type'] = [{'id': '300', 'name': 'declared-types', 'issueTypeIds': ['1'], 'defaultIssueTypeId': '1'}]
        with self.assertRaisesRegex(DeploymentError, 'reconciliation adapter required'):
            run_rest(self.docs, self.bindings, self.api, lambda event: None)
        self.assertFalse(any(method == 'POST' and path == '/rest/api/3/issuetypescheme' for method, path, _, _ in self.api.calls))

    def test_pagination_and_empty_intermediate_page_rejected(self):
        class API:
            def request(self, *args, **kwargs):
                start = kwargs['query']['startAt']
                return {'values': [{'id': start}] if start < 2 else [], 'total': 3, 'isLast': False}
        with self.assertRaisesRegex(DeploymentError, 'incomplete pagination'): pages(API(), '/rest/api/3/example')

    def test_token_requires_explicit_selection_and_cloud_url(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(DeploymentError, 'select PASCODE_AUTH_MODE'): Jira()
        env = {'PASCODE_AUTH_MODE': 'api_token_bootstrap', 'JIRA_API_BASE_URL': 'https://example.com', 'JIRA_API_EMAIL': 'person@example.com', 'JIRA_API_TOKEN': 'test-only'}
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaisesRegex(DeploymentError, 'unsupported Jira Cloud'): Jira()

    def test_existing_unknown_workflow_rules_are_not_discarded(self):
        self.api.add_terraform_resources(); run_rest(self.docs, self.bindings, self.api, lambda event: None)
        self.api.workflows[0]['transitions'][1]['actions'] = [{'ruleKey': 'unknown', 'parameters': {}}]
        self.assertTrue(any('unmodeled workflow rules' in g for g in resolve(self.docs, self.bindings, self.api)[4]['required_inputs']))

    def test_unknown_supplied_scheme_id_blocks_preparation(self):
        self.bindings['workflow_schemes']['engineering']['id'] = 'missing-id'
        self.assertTrue(any('ID/name does not match' in g for g in resolve(self.docs, self.bindings, self.api)[4]['required_inputs']))

    def generated_site(self):
        generated = generate(self.docs)
        self.api.types.extend([{'id': '101', 'name': '[System] Service request', 'description': 'native', 'subtask': False},
                               {'id': '102', 'name': '[System] Incident', 'description': 'native', 'subtask': False}])
        return generated

    def test_site_plan_allows_missing_permission_schemes_and_runtime_accounts(self):
        generated = self.generated_site()
        _, _, variables, _, plan = resolve(self.docs, generated, self.api)
        self.assertTrue(plan['ready'], plan['required_inputs'])
        self.assertEqual(len(plan['project_keys']), 6)
        self.assertEqual(len(plan['bootstrap_operations']), 5)
        self.assertTrue(all(sid is None for sid in variables['permission_scheme_ids'].values()))
        self.assertTrue(all(not task['blocks_provisioning'] and task['phase'] == 'agent_setup' for task in plan['human_tasks']))
        self.assertFalse(any(method == 'PUT' or (method == 'POST' and not path.endswith('/validation')) for method, path, _, _ in self.api.calls))

    def test_site_bootstrap_and_complete_rest_execution_then_reuse(self):
        generated = self.generated_site(); events = []
        run_bootstrap(self.docs, generated, self.api, events.append)
        self.assertEqual(len(events), 5)
        _, _, variables, _, plan = resolve(self.docs, generated, self.api)
        self.assertTrue(plan['ready'], plan['required_inputs'])
        self.assertTrue(all(sid is not None for sid in variables['permission_scheme_ids'].values()))
        for i, p in enumerate(self.docs['projects']['projects']):
            self.api.projects.append({'id': str(100 + i), 'key': p['key'], 'name': p['name'], 'projectTypeKey': p['project_type'], 'style': 'classic'})
        existing_names = {t['name'] for t in self.api.types}
        for n in sorted({n for p in self.docs['projects']['projects'] for n in p['work_types']} - existing_names - {'Subtask', 'Service Request', 'Incident'}):
            self.api.types.append({'id': str(200 + len(self.api.types)), 'name': n, 'description': 'new', 'subtask': False})
        self.api.project_permissions = variables['permission_scheme_ids']
        result = run_rest(self.docs, generated, self.api, lambda e: None)
        self.assertEqual(result['status'], 'project_configuration_verified')
        self.assertEqual(len(self.api.workflows), 9)
        self.assertEqual(len(self.api.schemes['work_type']), 4)
        self.assertEqual(len(self.api.schemes['workflow']), 4)
        # Runtime agents can join project roles without affecting provisioning readiness.
        self.api.runtime_actors = [{'actorUser': {'accountId': 'runtime-agent'}}]
        self.api.calls = []; repeated = []
        run_bootstrap(self.docs, generated, self.api, repeated.append)
        run_rest(self.docs, generated, self.api, repeated.append)
        self.assertTrue(all(e['action'] == 'reuse' for e in repeated))
        self.assertFalse(any(method == 'PUT' or (method == 'POST' and path not in ('/rest/api/3/workflows',) and not path.endswith('/validation')) for method, path, _, _ in self.api.calls))

    def test_existing_permission_drift_is_reported_without_overwriting(self):
        generated = self.generated_site()
        run_bootstrap(self.docs, generated, self.api, lambda e: None)
        self.api.permission_schemes[0]['permissions'].append({'permission': 'BROWSE_PROJECTS', 'holder': {'type': 'anyone'}})
        self.api.calls = []
        with self.assertRaisesRegex(DeploymentError, 'existing permission grants differ'):
            run_bootstrap(self.docs, generated, self.api, lambda e: None)
        self.assertFalse(any(method == 'PUT' for method, _, _, _ in self.api.calls))

    def test_default_role_membership_does_not_silently_grant_access(self):
        generated = self.generated_site()
        run_bootstrap(self.docs, generated, self.api, lambda e: None)
        self.api.roles[0]['actors'] = [{'actorUser': {'accountId': 'unexpected'}}]
        self.assertTrue(any('default actors' in g for g in resolve(self.docs, generated, self.api)[4]['required_inputs']))

    def test_native_platform_grants_are_recorded_but_other_extras_rejected(self):
        generated = self.generated_site()
        self.api.roles.append({'id': 10003, 'name': 'atlassian-addons-project-access', 'actors': []})
        self.api.inject_platform_grants = True; events = []
        run_bootstrap(self.docs, generated, self.api, events.append)
        self.assertTrue(all(e['platform_managed_grant_count'] == 2 for e in events if e['kind'] == 'permission_scheme'))
        self.assertTrue(resolve(self.docs, generated, self.api)[4]['ready'])
        self.api.permission_schemes[0]['permissions'].append({'permission': 'BROWSE_PROJECTS', 'holder': {'type': 'projectRole', 'value': '999'}})
        self.assertTrue(any('existing permission grants differ' in g for g in resolve(self.docs, generated, self.api)[4]['required_inputs']))

    def test_deferred_permissions_reuse_partial_projects_and_keep_target_profiles(self):
        generated = self.generated_site()
        generated['deployment'].update(project_keys=['PLAT'], defer_permission_assignment=True)
        self.api.add_terraform_resources()
        selected, _, variables, imports, plan = resolve(self.docs, generated, self.api)
        self.assertTrue(plan['ready'], plan['required_inputs'])
        self.assertEqual(variables['permission_scheme_ids'], {'PLAT': 17})
        self.assertIn({'to': 'jira_project.projects["PLAT"]', 'id': '100'}, imports)
        self.assertEqual(plan['deferred_permission_assignments'][0]['permission_profile'], 'internal-delivery')
        config = terraform_configuration(selected, defer_permission_assignment=True)
        resource = config['resource']['jira_project']['projects']
        self.assertNotIn('permission_scheme', resource)
        self.assertIn('permission_scheme', resource['lifecycle']['ignore_changes'])
        self.assertIn('permission_scheme', terraform_configuration(selected)['resource']['jira_project']['projects'])

    def test_default_permissions_do_not_block_workflows_or_claim_full_verification(self):
        generated = self.generated_site()
        generated['deployment'].update(project_keys=['PLAT'], defer_permission_assignment=True)
        self.api.add_terraform_resources(); events = []
        result = run_rest(self.docs, generated, self.api, events.append)
        self.assertEqual(result['status'], 'project_structure_verified_permissions_deferred')
        self.assertEqual(result['deferred_permission_assignments'][0]['observed_scheme_id'], 17)
        self.assertEqual(self.api.associations['workflow']['100'], '400')
        self.assertTrue(any(e['action'] == 'deferred' for e in events))
        self.assertFalse(any('/role/' in path or (method == 'PUT' and 'permissionscheme' in path)
                             for method, path, _, _ in self.api.calls))
        self.api.calls = []
        repeated = run_rest(self.docs, generated, self.api, lambda e: None)
        self.assertEqual(repeated['status'], result['status'])
        self.assertFalse(any(method == 'PUT' for method, _, _, _ in self.api.calls))

    def test_new_project_default_permissions_are_not_custom_scheme_ids(self):
        generated = self.generated_site()
        generated['deployment'].update(project_keys=['PLAT'], defer_permission_assignment=True)
        run_bootstrap(self.docs, generated, self.api, lambda e: None)
        _, _, variables, _, plan = resolve(self.docs, generated, self.api)
        self.assertIsNone(variables['permission_scheme_ids']['PLAT'])
        self.assertIsNotNone(plan['deferred_permission_assignments'][0]['desired_scheme_id'])

    def test_normal_apply_confirms_success_without_mutation_readbacks(self):
        self.api.add_terraform_resources()
        prepared = resolve(self.docs, self.bindings, self.api)
        self.api.calls = []; self.api.inject_bad_readback = True
        events = []
        result = apply_rest(self.docs, self.bindings, self.api, events.append, prepared=prepared)
        self.assertEqual(result['status'], 'project_operations_completed')
        self.assertFalse(result['remote_comparison_performed'])
        self.assertTrue(all(not e.get('verified', False) for e in events))
        self.assertEqual(len([c for c in self.api.calls if c[0] == 'GET']), 3)  # Two associations and one empty-project dependency check.
        self.assertFalse(any(path.endswith('/validation') or path.endswith('/workflows') or path.endswith('/workflows/search')
                             for _, path, _, _ in self.api.calls))
        self.assertEqual([e['confirmation'] for e in events], ['api_success'] * 5)

    def test_explicit_verify_detects_drift_and_never_mutates(self):
        self.api.add_terraform_resources()
        apply_rest(self.docs, self.bindings, self.api, lambda e: None)
        self.api.calls = []
        result = apply_rest(self.docs, self.bindings, self.api, lambda e: None, compare_only=True)
        self.assertTrue(result['remote_comparison_performed'])
        self.assertFalse(any(m in ('PUT', 'DELETE') or (m == 'POST' and p != '/rest/api/3/workflows') for m, p, _, _ in self.api.calls))
        self.api.associations['workflow']['100'] = 'wrong'; self.api.calls = []
        with self.assertRaisesRegex(DeploymentError, 'association differs'):
            apply_rest(self.docs, self.bindings, self.api, lambda e: None, compare_only=True)
        self.assertFalse(any(m == 'PUT' for m, _, _, _ in self.api.calls))

    def test_verify_missing_workflow_does_not_create_it(self):
        self.api.add_terraform_resources()
        with self.assertRaisesRegex(DeploymentError, 'workflow differs'):
            apply_rest(self.docs, self.bindings, self.api, lambda e: None, compare_only=True)
        self.assertFalse(any(m == 'POST' and p.endswith('/create') for m, p, _, _ in self.api.calls))

    def test_bootstrap_uses_prepared_discovery_and_success_response_ids(self):
        generated = self.generated_site()
        prepared = resolve(self.docs, generated, self.api); self.api.calls = []
        result = apply_bootstrap(self.docs, generated, self.api, lambda e: None, prepared=prepared)
        self.assertEqual(result['status'], 'bootstrap_operations_completed')
        self.assertTrue(all(m == 'POST' for m, _, _, _ in self.api.calls))
        self.assertTrue(all(sid is not None for sid in prepared[2]['permission_scheme_ids'].values()))

    def test_mapping_validation_is_not_repeated_by_normal_deployment(self):
        self.api.deny_validation = True
        self.assertTrue(resolve(self.docs, self.bindings, self.api)[4]['ready'])
        self.assertFalse(any(p.endswith('/validation') for _, p, _, _ in self.api.calls))

    def test_http_failure_is_not_recorded_as_completed(self):
        self.api.add_terraform_resources(); events = []
        prepared = resolve(self.docs, self.bindings, self.api)
        original = self.api.request
        def fail(method, path, *args, **kwargs):
            if path.endswith('/workflows/create'): raise DeploymentError('Jira HTTP 500')
            return original(method, path, *args, **kwargs)
        self.api.request = fail
        with self.assertRaisesRegex(DeploymentError, 'HTTP 500'):
            apply_rest(self.docs, self.bindings, self.api, events.append, prepared=prepared)
        self.assertEqual(events, [])

    def test_successful_terraform_state_supplies_execution_ids(self):
        self.api.add_terraform_resources()
        prepared = resolve(self.docs, self.bindings, self.api)
        state = {'resources': [
            {'mode': 'managed', 'type': 'jira_project', 'name': 'projects', 'instances': [
                {'index_key': 'PLAT', 'attributes': {'id': '100', 'key': 'PLAT', 'permission_scheme': 17}}]},
            {'mode': 'managed', 'type': 'jira_issue_type', 'name': 'work_types', 'instances': [
                {'index_key': n, 'attributes': {'id': prepared[1]['issue_types'][n]['id'],
                 'is_subtask': n == 'Subtask'}} for n in self.docs['projects']['projects'][1]['work_types']]}]}
        hydrated = terraform_bindings(prepared, state)
        self.assertEqual(hydrated[1]['projects'], {'PLAT': '100'})
        self.assertEqual(len(hydrated[1]['issue_types']), 6)
        state['resources'][0]['instances'] = []
        with self.assertRaisesRegex(DeploymentError, 'every selected project'):
            terraform_bindings(prepared, state)

    def test_async_acceptance_does_not_claim_completion(self):
        import io
        class Response(io.BytesIO):
            status = 202
        env = {'PASCODE_AUTH_MODE': 'api_token_bootstrap', 'JIRA_API_BASE_URL': 'https://example.atlassian.net',
               'JIRA_API_EMAIL': 'person@example.com', 'JIRA_API_TOKEN': 'test-only'}
        with patch.dict('os.environ', env, clear=True): api = Jira()
        with patch.object(api.opener, 'open', return_value=Response(b'{"taskId":"pending"}')):
            with self.assertRaisesRegex(DeploymentError, 'asynchronous operation'):
                api.request('POST', '/rest/api/3/workflows/create', {})

    def test_verify_entrypoint_needs_no_previous_plan_or_terraform_state(self):
        import io
        import tempfile
        from deployment import main
        self.api.add_terraform_resources()
        apply_rest(self.docs, self.bindings, self.api, lambda e: None)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory); inputs = work / 'input.json'
            inputs.write_text(json.dumps(self.bindings))
            argv = ['deployment.py', 'verify', '--root', '/inputs', '--workdir', directory, '--bindings', str(inputs)]
            with patch('sys.argv', argv), patch('deployment.Jira', return_value=self.api), patch('sys.stdout', new=io.StringIO()):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads((work / 'verification-result.json').read_text())['status'], 'project_configuration_verified')
            self.assertFalse((work / 'deployment-plan.json').exists())
            self.assertFalse((work / 'terraform').exists())


if __name__ == '__main__': unittest.main()
