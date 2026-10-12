"""Read-only, strict YAML/schema validation with Jira relationship checks."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry


class StrictLoader(yaml.SafeLoader):
    pass


StrictLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for key, entries in StrictLoader.yaml_implicit_resolvers.items():
    StrictLoader.yaml_implicit_resolvers[key] = [
        item for item in entries if item[0] != 'tag:yaml.org,2002:timestamp'
    ]


def mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError('Duplicate or non-string mapping key')
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor('tag:yaml.org,2002:map', mapping)


def load(path, boundary=None):
    if boundary is not None and not path.resolve().is_relative_to(Path(boundary).resolve()):
        raise ValueError('Input escapes the selected root')
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('YAML file exceeds 4 MiB')
    value = yaml.load(raw, Loader=StrictLoader)
    json.dumps(value, allow_nan=False)  # Reject cycles and non-JSON YAML values.
    return value, hashlib.sha256(raw).hexdigest()


def issue(code, file, field='$', line=None):
    result = {'code': code, 'file': str(file), 'field': field}
    if line is not None:
        result['line'] = line
    return result


def jira_checks(documents):
    errors = []
    projects = documents.get('projects.yaml', {}).get('projects', [])
    schemes = documents.get('permission-schemes.yaml', {}).get('permission_schemes', {})
    workflows = documents.get('workflow-definitions.yaml', {}).get('workflow_definitions', {})
    identities = documents.get('service-account-registry.yaml', {})
    service = identities.get('service_account_registry', {})
    users = identities.get('user_accounts', {})
    keys = set()
    for index, project in enumerate(projects):
        key = project.get('jira_key', project.get('key'))
        if not isinstance(key, str) or key in keys:
            errors.append(issue('invalid_or_duplicate_project_key', 'projects.yaml', f'$.projects[{index}]'))
        else:
            keys.add(key)
        for field, definitions in [('permission_scheme', schemes), ('workflow_scheme', workflows)]:
            if project.get(field) not in definitions:
                errors.append(issue('unresolved_reference', 'projects.yaml', f'$.projects[{index}].{field}'))
    for name, account in service.items():
        bindings = account.get('project_role_bindings', {})
        access = account.get('project_access', account.get('access', {}))
        allowed = set()
        denied = set(access.get('denied', []))
        for role, values in access.items():
            if isinstance(values, list):
                for key in values:
                    if key not in keys:
                        errors.append(issue('unknown_project', 'service-account-registry.yaml',
                                            f'$.service_account_registry.{name}.{role}'))
                if role != 'denied':
                    allowed.update(values)
        if allowed - bindings.keys() or denied.intersection(bindings):
            errors.append(issue('access_binding_mismatch', 'service-account-registry.yaml',
                                f'$.service_account_registry.{name}.project_role_bindings'))
        for key in bindings:
            if key not in keys:
                errors.append(issue('unknown_project', 'service-account-registry.yaml',
                                    f'$.service_account_registry.{name}.project_role_bindings'))
    routes = documents.get('api_auth_routing.yaml', {}).get('api_auth_routing', {})
    for name, route in routes.items():
        identity = route.get('canonical_identity')
        if identity not in service and identity not in users:
            errors.append(issue('unknown_identity', 'api_auth_routing.yaml', f'$.api_auth_routing.{name}'))
    return errors


def validate(root, schema_root=None, family=None):
    root = Path(root)
    schema_root = Path(schema_root or root)
    families = [root / family] if family else sorted(root.glob('*-as-code'))
    results = []
    if not families:
        results.append({'file': '.', 'errors': [issue('no_inputs', '.')]})
    for directory in families:
        paths = sorted(set(directory.glob('*.yaml')) | set(directory.glob('*.yml')) |
                       set((directory / 'config').glob('*.yaml')) |
                       set((directory / 'config').glob('*.yml')))
        if not paths:
            results.append({'file': directory.name, 'errors': [issue('no_inputs', directory.name)]})
        documents = {}
        for path in paths:
            relative = str(path.relative_to(root))
            record = {'file': relative, 'errors': []}
            results.append(record)
            try:
                data, record['source_sha256'] = load(path, root)
                if not isinstance(data, dict):
                    raise ValueError('Configuration must be an object')
                documents[path.name] = data
            except (ValueError, TypeError, RecursionError, OSError, yaml.YAMLError) as exc:
                mark = getattr(exc, 'problem_mark', None)
                record['errors'].append(issue('invalid_yaml', relative,
                                              line=mark.line + 1 if mark else None))
                continue
            schema = schema_root / directory.name / 'shapes' / (path.stem + '.schema.yaml')
            if not schema.is_file():
                record['errors'].append(issue('missing_schema', relative))
                continue
            try:
                contract, record['schema_sha256'] = load(schema, schema_root)
                validator = validator_for(contract)
                validator.check_schema(contract)
                # Empty registry prevents remote reference retrieval.
                checker = validator(contract, format_checker=FormatChecker(), registry=Registry())
                for error in checker.iter_errors(data):
                    field = '$' + ''.join(f'[{part}]' if isinstance(part, int) else '.' + part
                                          for part in error.absolute_path)
                    record['errors'].append(issue('schema_' + str(error.validator), relative, field))
            except Exception:
                record['errors'].append(issue('invalid_or_unresolved_schema', relative))
        if directory.name == 'jira-as-code' and documents:
            try:
                for error in jira_checks(documents):
                    error['file'] = f"jira-as-code/config/{error['file']}"
                    results.append({'file': error['file'], 'errors': [error]})
            except (AttributeError, TypeError, ValueError, KeyError):
                results.append({'file': directory.name,
                                'errors': [issue('invalid_relationship_structure', directory.name)]})
    errors = sum(len(record['errors']) for record in results)
    return {'conforms': bool(results) and errors == 0, 'errors': errors,
            'files': sum('source_sha256' in record for record in results), 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/input'))
    parser.add_argument('--schema-root', type=Path)
    parser.add_argument('--family', choices=['jira-as-code', 'github-as-code',
                                           'governance-as-code', 'llm-as-code'])
    args = parser.parse_args()
    report = validate(args.root, args.schema_root, args.family)
    print(json.dumps(report, indent=2))
    return 0 if report['conforms'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
