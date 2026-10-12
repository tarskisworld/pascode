"""Dated coverage evidence for current schemas and implementation; no Jira calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_fields(schema, path=''):
    if 'properties' in schema:
        if path:
            yield path
        for name, child in schema['properties'].items():
            yield from schema_fields(child, f'{path}.{name}' if path else name)
    elif schema.get('type') == 'array' and schema['items'].get('type') == 'object':
        yield path
        yield from schema_fields(schema['items'], path + '[]')
    elif isinstance(schema.get('additionalProperties'), dict):
        yield path
        yield from schema_fields(schema['additionalProperties'], path + '.*')
    else:
        yield path


def coverage_rules():
    rules = {}

    def add(contract, fields, status, implementation, operations, bindings, gap):
        for field in fields:
            key = (contract + '.yaml', field)
            if key in rules:
                raise ValueError(f'duplicate coverage rule: {key}')
            rules[key] = {
                'coverage': status,
                'implementation': implementation,
                'operation_support': operations,
                'required_inputs': bindings,
                'remaining_gap': gap,
            }

    add('projects', ['projects[]', 'projects[].key', 'projects[].name'],
        'provider_candidate', 'runner.main -> jira_project; fourplusone/jira 0.1.16',
        {'create': 'generated', 'update': 'provider_candidate', 'reuse': 'manual_import', 'association': 'not_applicable'},
        ['lead_account_id', 'permission_scheme_id', 'template_key', 'provider_auth', 'state_backend'],
        'Discovery/import and shared execution are missing; Cloud create/update has not been tested by this runner.')
    add('projects', ['projects[].project_type'],
        'partial', 'runner.validate and runner.main -> jira_project.project_type_key',
        {'create': 'generated', 'update': 'migration_not_mapped', 'reuse': 'compatibility_check_missing'},
        ['product_entitlement', 'template_key', 'observed_project_type'],
        'General entitlement and existing-project compatibility checks are missing; one dated JSM entitlement observation is evidence only.')
    add('projects', ['projects[].management'],
        'partial', 'projects.schema.json company-managed const; runner.main template binding',
        {'create': 'template_dependent', 'update': 'migration_not_mapped', 'reuse': 'compatibility_check_missing'},
        ['verified_company_managed_template', 'observed_management_mode'],
        'No direct management-mode API field is emitted; supplied template and existing project mode still need verification.')
    add('projects', ['projects[].template'],
        'partial', 'runner.validate; runner.main -> var.project_template_keys',
        {'create': 'manual_template_binding', 'update': 'not_a_retheming_operation', 'reuse': 'no_template_recreation'},
        ['verified_template_key_per_project'],
        'Symbolic template-to-native-key resolution is supplied manually and is not checked against desired management/type.')
    add('projects', ['projects[].work_type_scheme'],
        'payload_mapping', 'adapters.work_type_scheme_request and scheme_association; rest_plan',
        {'create': 'mapped', 'update': 'missing', 'reuse': 'existing_id_rejected_for_creation', 'association': 'mapped'},
        ['scheme_name', 'default_work_type', 'issue_type_ids_and_subtask_metadata', 'project_and_scheme_ids'],
        'Existing scheme reconciliation, discovery and association migration checks are missing.')
    add('projects', ['projects[].work_types'],
        'payload_mapping', 'runner.main -> jira_issue_type; adapters.work_type_scheme_request',
        {'create': 'generated', 'update': 'provider_candidate', 'reuse': 'manual_import', 'association': 'ordered_new_scheme_membership_mapped'},
        ['description_and_is_subtask_per_type', 'existing_type_inventory', 'scheme_members_and_default'],
        'Work-type metadata is required separately; import, existing membership reconciliation and execution are missing.')
    add('projects', ['projects[].permission_profile'],
        'missing_declaration_and_adapter', 'runner.main consumes permission_scheme_ids only; audit/permission-plan.json is a proposal',
        {'create': 'missing', 'update': 'missing', 'reuse': 'manual_id_only', 'association': 'provider_argument_only'},
        ['profile_grant_definition', 'concrete_permission_holders', 'permission_scheme_ids'],
        'The referenced profiles do not have schema-backed grant declarations or permission-scheme/grant adapters.')

    add('service-account-registry', ['service_account_registry.*'],
        'missing', 'runner.mapping records blocked atlassian_admin account resources',
        {'create': 'missing', 'update': 'missing', 'reuse': 'missing', 'association': 'missing'},
        ['supported_native_service_account_method', 'admin_auth', 'entitlements', 'observed_account_id'],
        'Naming records are not Atlassian accounts; no native account provisioning/reuse adapter is implemented.')
    add('service-account-registry', ['service_account_registry.*.site'],
        'checked_reference', 'runner.validate verifies account.site equals site.base_url',
        {'create': 'not_required', 'update': 'not_required', 'reuse': 'existing_site_reference', 'association': 'account_site_access_missing'},
        ['existing_site_context'],
        'Equality validation does not grant the account site/product access.')
    add('service-account-registry', ['service_account_registry.*.auth.preferred', 'service_account_registry.*.auth.api_service_account_override'],
        'unenforced_policy', 'runner.mapping retains auth selectors',
        {'create': 'not_required_for_selector', 'update': 'not_applicable', 'reuse': 'credential_selection_missing'},
        ['explicit_auth_selection', 'supported_oauth_or_token_credentials'],
        'General account authentication selection and explicit override enforcement are missing; bootstrap launcher is a separate configured human identity.')
    add('service-account-registry', ['service_account_registry.*.auth.secret_ref'],
        'unresolved_reference', 'runner.mapping retains secret reference; bootstrap launcher reads its separate gopass entry',
        {'create': 'not_required_for_reference', 'reuse': 'account_secret_lookup_missing'},
        ['existing_secret_store_entry'],
        'No account-specific resolver or new credential storage lifecycle is implemented; do not manufacture a token from a path string.')
    add('service-account-registry', ['service_account_registry.*.account_id', 'service_account_registry.*.account_email'],
        'unresolved_binding', 'service-account schema accepts observations; runner.mapping retains them',
        {'create': 'not_a_separate_resource', 'reuse': 'identity_discovery_missing'},
        ['verified_account_inventory'],
        'All current observations are null; identity lookup, native email observation and binding persistence are missing.')
    for role in ('contributor', 'agent', 'read_only', 'admin_during_deployment'):
        add('service-account-registry', ['service_account_registry.*.project_access.' + role],
            'missing', 'runner.validate checks references/conflicting grants; runner.mapping retains access lists',
            {'create': 'grant_missing', 'update': 'grant_reconciliation_missing', 'reuse': 'role_discovery_missing', 'association': 'missing'},
            ['account_id', 'project_id', 'explicit_role_or_permission_holder'] + (['JSM_agent_entitlement'] if role == 'agent' else []),
            ('Read-only is currently unused; its future access adapter is still missing.' if role == 'read_only' else
             'Temporary grant and guaranteed administrative revocation are missing.' if role == 'admin_during_deployment' else
             'Both project access and separate JSM agent entitlement handling are missing.' if role == 'agent' else
             'No concrete project grant adapter or effective-access verification is implemented.'))
    add('service-account-registry', ['service_account_registry.*.project_access.denied', 'service_account_registry.*.restrictions'],
        'unenforced_constraint', 'runner.validate checks declared grant/deny overlap only',
        {'create': 'no_deny_resource', 'update': 'conflicting_grant_revocation_missing', 'reuse': 'effective_access_verification_missing'},
        ['effective_project_and_global_access_inventory', 'grant_lifecycle_context'],
        'Live additive permissions and no_persistent_admin_grant cleanup are not enforced; empty restrictions request nothing.')

    add('site', ['site.base_url'],
        'mapped_reference', 'runner.mapping site; explicit Terraform jira_api_base_url variable',
        {'create': 'not_required', 'reuse': 'existing_site_context'},
        ['explicit_site_or_scoped_gateway_context'],
        'General execution must verify supplied gateway/site context; it does not provision an Atlassian site.')
    add('site', ['site.auth_default', 'site.api_service_account_override_requires_explicit_selection'],
        'unenforced_policy', 'runner.mapping site-policy status declared',
        {'create': 'not_required_for_selector', 'reuse': 'general_auth_selection_missing'},
        ['explicit_execution_auth_context'],
        'General OAuth selection and explicit API-service-account override checks are not implemented.')
    add('site', ['site.account_email_domain'],
        'no_current_action', 'schema accepts an optional email naming policy',
        {'create': 'not_a_domain_or_mailbox_declaration'}, [],
        'Currently null. Any future email proposal uses the naming tool; no adapter may rewrite an Atlassian-generated native email.')
    add('site', ['deployment.reuse_existing_resources_after_discovery'],
        'partial_policy', 'adapters reuse supplied status IDs; reject existing schemes for duplicate creation; Terraform prevent_destroy',
        {'create': 'guarded_only_by_supplied_bindings', 'reuse': 'general_discovery_missing'},
        ['fresh_complete_resource_inventory', 'imported_Terraform_state'],
        'Supplied bindings permit some reuse; absence from a bindings file is not proof a resource is absent in Jira.')
    add('site', ['deployment.credentials_in_repository'],
        'partial_policy', 'bindings.schema.json rejects unknown fields; Terraform token variable is sensitive; bootstrap launcher uses gopass',
        {'create': 'no_remote_resource', 'verification': 'general_secret_leak_check_missing'},
        ['runtime_secret_injection', 'safe_state_and_logging_configuration'],
        'Current design keeps credentials external; sensitive=true alone does not guarantee safe state/logs or enforce all future outputs.')

    add('workflow-definitions', ['workflow_definitions.*', 'workflow_definitions.*.initial_status'],
        'payload_mapping', 'adapters.workflow_request; runner.validate',
        {'create': 'mapped', 'update': 'partial_observed_topology_only', 'reuse': 'explicit_existing_binding', 'association': 'initial_transition_mapped'},
        ['workflow_name', 'status_inventory', 'resolution_ids', 'existing_workflow_version_and_transition_ids_for_update'],
        'Shared live execution, topology migration and preservation of unmodeled properties are missing; initial DONE is rejected.')
    add('workflow-definitions', ['workflow_definitions.*.statuses.*'],
        'payload_mapping', 'adapters.workflow_request status payload and category conflict check',
        {'create': 'mapped_inside_new_workflow', 'update': 'category_migration_rejected', 'reuse': 'supplied_compatible_ids', 'association': 'mapped'},
        ['observed_status_ids_and_categories'],
        'No shared status discovery; workflow updates require observed IDs for all statuses. Missing bindings may otherwise propose duplicate status creation.')
    add('workflow-definitions', ['workflow_definitions.*.transitions[]', 'workflow_definitions.*.transitions[].name', 'workflow_definitions.*.transitions[].from', 'workflow_definitions.*.transitions[].to'],
        'payload_mapping', 'adapters.workflow_request; runner.validate graph references/reachability',
        {'create': 'mapped_in_workflow', 'update': 'observed_transition_ids_required', 'reuse': 'observed_identity_only', 'association': 'directed_status_links_mapped'},
        ['existing_transition_ids_for_updates', 'status_bindings'],
        'Add/remove transition reconciliation, live execution and unmodeled rule/layout preservation are missing.')
    add('workflow-definitions', ['workflow_definitions.*.transitions[].actor'],
        'no_current_action', 'schema contributor const; adapters.workflow_request emits ordinary permissions with conditions=None',
        {'create': 'no_extra_identity_role_or_approval_rule'}, [],
        'Underlying project permission grants need separate implementation; actor label creates no identity or role.')
    add('workflow-definitions', ['workflow_definitions.*.transitions[].validators'],
        'no_current_action', 'adapters.workflow_request rejects nonempty unsupported validators',
        {'create': 'none_for_current_empty_lists', 'future_rules': 'rejected_until_supported'}, [],
        'All current lists are empty. Schema permits future strings, but no nonempty validator adapter exists.')
    add('workflow-definitions', ['workflow_definitions.*.transitions[].effects'],
        'payload_mapping', 'adapters.workflow_request system:update-field; runner.workflow_control_errors',
        {'create': 'set_and_clear_resolution_mapped', 'update': 'mapped_with_observed_ids', 'verification': 'declaration_checks_only'},
        ['resolution_id_for_set_resolution_destinations'],
        'Jira validation evidence exists for delivery update; actual transition behavior on issues is not tested.')
    add('workflow-definitions', ['workflow_schemes.*', 'workflow_schemes.*.default', 'workflow_schemes.*.overrides.*'],
        'payload_mapping', 'adapters.workflow_scheme_request and scheme_association',
        {'create': 'mapped', 'update': 'missing', 'reuse': 'existing_id_rejected_for_creation', 'association': 'mapped'},
        ['workflow_names', 'issue_type_ids', 'scheme_name', 'project_and_scheme_ids'],
        'Existing scheme/draft reconciliation and populated-project migration checks are missing; mapping uses workflow names and issue type IDs.')
    add('workflow-definitions', ['controls.blocked_representation'],
        'unverified_policy', 'runner.mapping reports prerequisite checks as unimplemented',
        {'create': 'conditional_prerequisites_only', 'verification': 'missing'},
        ['flag_field_and_dependency_link_inventory', 'project_context_and_screen_checks'],
        'No prerequisites have been checked by the runner. This does not declare another status, issue or approval resource.')
    add('workflow-definitions', ['controls.done_sets_resolution', 'controls.reopen_clears_resolution'],
        'checked_and_payload_mapped', 'runner.workflow_control_errors; adapters.workflow_request',
        {'create': 'no_separate_resource', 'configuration': 'transition_effects_mapped', 'verification': 'declaration_consistency_tested'},
        ['resolution_ids_for_terminal_destinations'],
        'No live issue-transition behavior verification; shared live executor is missing.')
    return rules


def audit(root, runtime, output):
    family = root / 'jira-as-code'
    classification_path = family / 'audit/field-instantiation-audit.json'
    classification = json.loads(classification_path.read_text())
    for name, expected in classification['source_sha256'].items():
        if digest(family / 'config' / name) != expected:
            raise ValueError(f'stale field classification: {name}; refresh it before auditing coverage')
    schema_paths = {}
    for path in sorted((family / 'shapes').glob('*.schema.json')):
        contract = path.name.removesuffix('.schema.json') + '.yaml'
        schema_paths.update({(contract, field): path for field in schema_fields(json.loads(path.read_text()))})
    classified = {(r['contract'], r['field']) for r in classification['fields']}
    if classified != set(schema_paths) or len(classified) != len(classification['fields']):
        raise ValueError('field classification does not exactly cover current schemas')
    rules = coverage_rules()
    records = []
    for field in classification['fields']:
        key = (field['contract'], field['field'])
        if field['kind'] in {'container', 'metadata'}:
            detail = {
                'coverage': 'no_adapter_required',
                'implementation': 'schema structure / retained bookkeeping',
                'operation_support': {'create': 'not_a_resource'},
                'required_inputs': [],
                'remaining_gap': 'Metadata values are not evidence of live deployment.' if field['kind'] == 'metadata' else 'Contained fields are audited separately.',
            }
        else:
            if key not in rules:
                raise ValueError(f'unclassified implementation coverage: {key}')
            detail = rules.pop(key)
        records.append({**field, **detail, 'shared_live_execution_implemented': False})
    if rules:
        raise ValueError(f'coverage rules outside current schemas: {sorted(rules)}')
    source_files = ['runner.py', 'adapters.py', 'bindings.schema.json', 'tests.py', 'adapter_tests.py', 'audit_coverage.py']
    report = {
        'audit_date': datetime.now(timezone.utc).date().isoformat(),
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': classification['scope'],
        'meaning': 'Coverage evidence, not a provisioning plan. Field paths overlap parent actions; counts are not independent resource counts or a deployment percentage.',
        'all_schema_fields_audited': True,
        'field_count': len(records),
        'by_coverage': dict(Counter(r['coverage'] for r in records)),
        'config_sha256': classification['source_sha256'],
        'schema_sha256': {p.name: digest(p) for p in sorted(set(schema_paths.values()))},
        'classification_sha256': digest(classification_path),
        'runtime_sha256': {name: digest(runtime / name) for name in source_files},
        'deployable': False,
        'shared_live_executor_implemented': False,
        'evidence': {
            'offline_tests': 'tests.py and adapter_tests.py; run independently of this audit',
            'provider': 'audit/terraform-provider-schema.json and pinned provider source snapshots',
            'live_payload_validation': 'audit/shared-workflow-adapter-validation.json; delivery only, no apply',
            'separate_live_pilot': 'audit/delivery-verification.json; MCP pilot is not evidence of shared executor coverage',
        },
        'next_steps': [
            'Define schema-backed permission profiles/grants and explicit work-type metadata; do not promote audit proposal fields silently.',
            'Resolve service account creation/reuse and separate product entitlements; bind actual IDs.',
            'Implement fresh inventory/diff, Terraform import/state handling, existing scheme and workflow topology reconciliation.',
            'Implement execution policies, access/lifecycle checks, ordered API/Terraform execution and read-back verification.',
            'Test one fully bound project, resolution/reopen issue behavior and exclusion of denied accounts.',
        ],
        'fields': records,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / 'implementation-coverage.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = [
        '# Jira field implementation coverage', '', report['meaning'], '',
        f'Audited all {len(records)} schema paths. Snapshot date: {report["audit_date"]}. Source hashes are recorded in the JSON report.', '',
        'Projects/work types have generated Terraform candidates. Workflows and new schemes/associations have REST payload adapters. The shared live executor, discovery/import and permission/account adapters remain incomplete.', '',
        'Resolution policy consistency is now checked locally and translated into workflow effects. Flag/dependency prerequisites remain unverified. Site/auth selectors are declared values with incomplete general enforcement.', '',
        '## Coverage labels', '',
        '| Label | Field paths |', '|---|---:|',
        *[f'| {label.replace("_", " ")} | {count} |' for label, count in report['by_coverage'].items()], '',
        'No percentage is reported: metadata needs no provisioning, several paths configure the same resource, and payload mapping does not imply execution/reconciliation support.',
    ]
    for contract in classification['source_sha256']:
        lines += ['', f'## {contract}', '', '| Field | Coverage / implementation | Required bindings / remaining gap |', '|---|---|---|']
        for row in records:
            if row['contract'] != contract:
                continue
            inputs = ', '.join(row['required_inputs']) or 'No extra binding'
            lines.append(f'| `{row["field"]}` | {row["coverage"].replace("_", " ")}; {row["implementation"]} | {inputs}. {row["remaining_gap"]} |')
    lines += ['', '## Execution boundary', '',
              'The JSON rows separately record create, update, reuse and association support. Shared live execution is not implemented for any resource family. Current evidence includes offline tests, provider configuration validation and a delivery workflow REST validation. A separately executed MCP delivery pilot does not establish full project, permission or account provisioning coverage.', '',
              '## Next implementation order', '']
    lines += [f'{i}. {step}' for i, step in enumerate(report['next_steps'], 1)]
    lines += ['', '## Reproduce', '', 'Run with the pinned validation image, read-only mounts of pascode and this runtime, and a writable output directory:', '',
              '```sh', 'python /runtime/audit_coverage.py --root /inputs --output /output', '```', '',
              'The command rejects stale configuration classifications, mismatched schema paths and fields without coverage annotations. It makes no network requests. After implementation changes, rerun it to refresh runtime hashes. Audit generation does not itself run tests.']
    (output / 'implementation-coverage.md').write_text('\n'.join(lines) + '\n')
    return {k: report[k] for k in ('field_count', 'all_schema_fields_audited', 'by_coverage', 'deployable')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.root, Path(__file__).parent, args.output), indent=2))
