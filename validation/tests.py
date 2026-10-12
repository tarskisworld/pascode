import tempfile
import unittest
from pathlib import Path

from worker import jira_checks, load, validate


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.family = self.root / 'llm-as-code'
        (self.family / 'config').mkdir(parents=True)
        (self.family / 'shapes').mkdir()
        self.config = self.family / 'config/providers.yaml'
        self.schema = self.family / 'shapes/providers.schema.yaml'
        self.config.write_text('email: bot@example.com\n')
        self.schema.write_text('type: object\nrequired: [email]\nproperties:\n'
                               '  email: {type: string, format: email}\nadditionalProperties: false\n')

    def test_valid(self):
        self.assertTrue(validate(self.root)['conforms'])

    def test_missing_schema_fails(self):
        self.schema.unlink()
        self.assertFalse(validate(self.root)['conforms'])

    def test_missing_field_and_typo(self):
        self.config.write_text('emial: bot@example.com\n')
        report = validate(self.root)
        self.assertEqual(report['errors'], 2)

    def test_format(self):
        self.config.write_text('email: invalid\n')
        self.assertFalse(validate(self.root)['conforms'])

    def test_duplicate_yaml(self):
        self.config.write_text('email: one\nemail: two\n')
        self.assertEqual(validate(self.root)['results'][0]['errors'][0]['code'], 'invalid_yaml')

    def test_dates_remain_strings(self):
        self.config.write_text('expiry: 2026-12-31\n')
        self.assertEqual(load(self.config)[0]['expiry'], '2026-12-31')

    def test_unsafe_tags(self):
        self.config.write_text('email: !!python/object:example {}\n')
        self.assertFalse(validate(self.root)['conforms'])

    def test_remote_refs_fail_without_network(self):
        self.schema.write_text('$ref: https://invalid.example/schema\n')
        self.assertFalse(validate(self.root)['conforms'])

    def test_empty_selection_fails(self):
        self.assertFalse(validate(self.root, family='jira-as-code')['conforms'])

    def test_empty_root_reports_error(self):
        report = validate(self.family / 'shapes')
        self.assertFalse(report['conforms'])
        self.assertEqual(report['errors'], 1)

    def test_symlink_outside_root_fails(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        outside = Path(other.name) / 'outside.yaml'
        outside.write_text('email: bot@example.com\n')
        self.config.unlink()
        self.config.symlink_to(outside)
        report = validate(self.root)
        self.assertFalse(report['conforms'])

    def test_unresolved_workflow(self):
        documents = {'projects.yaml': {'projects': [{'key': 'ENG',
                    'permission_scheme': 'open', 'workflow_scheme': 'missing'}]},
                     'permission-schemes.yaml': {'permission_schemes': {'open': {}}}}
        self.assertEqual(jira_checks(documents)[0]['code'], 'unresolved_reference')

    def test_denied_project_role_binding(self):
        documents = {'projects.yaml': {'projects': [{'key': 'FIN',
                    'permission_scheme': 'open', 'workflow_scheme': 'flow'}]},
                     'permission-schemes.yaml': {'permission_schemes': {'open': {}}},
                     'workflow-definitions.yaml': {'workflow_definitions': {'flow': {}}},
                     'service-account-registry.yaml': {'service_account_registry': {'bot': {
                         'project_access': {'denied': ['FIN']},
                         'project_role_bindings': {'FIN': 'Contributors'}}}}}
        self.assertEqual(jira_checks(documents)[0]['code'], 'access_binding_mismatch')


if __name__ == '__main__':
    unittest.main()
