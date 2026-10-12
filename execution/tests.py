import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from runner import validate,mapping,workflow_control_errors
class MappingTests(unittest.TestCase):
    def setUp(self):self.docs,self.errors=validate(Path('/inputs'))
    def test_direct_contracts(self):
        self.assertEqual(self.errors,[])
        self.assertEqual(set(self.docs),{'site','projects','workflow-definitions','service-account-registry','permission-profiles'})
    def test_ordinary_workflows_have_no_approval_gates(self):
        for workflow in self.docs['workflow-definitions']['workflow_definitions'].values():
            self.assertNotIn('Awaiting Approval',workflow['statuses'])
            for transition in workflow['transitions']:
                self.assertEqual(transition['actor'],'contributor')
                self.assertEqual(transition['validators'],[])
                self.assertTrue(set(transition['effects'])<={'set_resolution','clear_resolution'})
    def test_done_transition_allowed_for_contributor(self):
        self.assertTrue(any(t['actor']=='contributor' and w['statuses'][t['to']]=='DONE' for w in self.docs['workflow-definitions']['workflow_definitions'].values() for t in w['transitions']))
    def test_all_projects_and_accounts_mapped(self):
        ids={r['id'] for r in mapping(self.docs)['resources']}
        self.assertTrue({f'project:{p["key"]}' for p in self.docs['projects']['projects']}<=ids)
        self.assertTrue({f'account:{a}' for a in self.docs['service-account-registry']['service_account_registry']}<=ids)
    def test_blockers_preserved(self):
        report=mapping(self.docs)
        self.assertFalse(report['deployable']);self.assertTrue(report['blockers']);self.assertTrue(report['unmapped_control_contracts'])
    def test_deterministic_mapping(self):self.assertEqual(mapping(self.docs),mapping(copy.deepcopy(self.docs)))
    def test_no_workflow_rules_dropped(self):
        report=mapping(self.docs)
        for resource in report['resources']:
            if resource['id'].startswith('workflow:'):
                self.assertEqual(resource['desired'],self.docs['workflow-definitions']['workflow_definitions'][resource['id'].split(':')[1]])
    def test_declared_resolution_controls_match_effects(self):
        self.assertEqual(workflow_control_errors(self.docs['workflow-definitions']),[])
    def test_missing_terminal_resolution_rejected(self):
        docs=copy.deepcopy(self.docs['workflow-definitions'])
        workflow=docs['workflow_definitions']['delivery']
        transition=next(t for t in workflow['transitions'] if workflow['statuses'][t['to']]=='DONE')
        transition['effects']=[]
        self.assertTrue(any('must set_resolution' in e for e in workflow_control_errors(docs)))
    def test_missing_reopen_resolution_clear_rejected(self):
        docs=copy.deepcopy(self.docs['workflow-definitions'])
        workflow=docs['workflow_definitions']['delivery']
        transition=next(t for t in workflow['transitions'] if workflow['statuses'][t['from']]=='DONE' and workflow['statuses'][t['to']]!='DONE')
        transition['effects']=[]
        self.assertTrue(any('must clear_resolution' in e for e in workflow_control_errors(docs)))
    def test_resolution_effect_on_wrong_category_rejected(self):
        docs=copy.deepcopy(self.docs['workflow-definitions'])
        workflow=docs['workflow_definitions']['delivery']
        transition=next(t for t in workflow['transitions'] if workflow['statuses'][t['to']]!='DONE')
        transition['effects']=['set_resolution']
        self.assertTrue(any('requires a DONE destination' in e for e in workflow_control_errors(docs)))
    def test_conflicting_resolution_effects_rejected(self):
        docs=copy.deepcopy(self.docs['workflow-definitions'])
        docs['workflow_definitions']['delivery']['transitions'][0]['effects']=['set_resolution','clear_resolution']
        self.assertTrue(any('conflicting resolution effects' in e for e in workflow_control_errors(docs)))
    def test_initial_done_refused_until_initial_effect_supported(self):
        docs=copy.deepcopy(self.docs['workflow-definitions'])
        workflow=docs['workflow_definitions']['delivery']
        workflow['initial_status']=next(n for n,c in workflow['statuses'].items() if c=='DONE')
        self.assertTrue(any('unsupported initial resolution effect' in e for e in workflow_control_errors(docs)))
    def test_policy_report_distinguishes_mapping_from_enforcement(self):
        report=mapping(self.docs)
        self.assertEqual(report['control_contracts']['done_sets_resolution']['status'],'validated_and_mapped')
        self.assertFalse(report['control_contracts']['done_sets_resolution']['live_issue_behavior_verified'])
        self.assertEqual(report['control_contracts']['blocked_representation']['status'],'unimplemented')
        self.assertEqual(next(r for r in report['resources'] if r['id']=='site-policy')['status'],'declared')
    def test_validate_rejects_inconsistent_resolution_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for part in ('config','shapes'):
                shutil.copytree(Path('/inputs/jira-as-code')/part,root/'jira-as-code'/part)
            docs=copy.deepcopy(self.docs['workflow-definitions'])
            workflow=docs['workflow_definitions']['delivery']
            next(t for t in workflow['transitions'] if workflow['statuses'][t['to']]=='DONE')['effects']=[]
            (root/'jira-as-code/config/workflow-definitions.yaml').write_text(json.dumps(docs))
            _,errors=validate(root)
            self.assertTrue(any('must set_resolution' in e for e in errors))
if __name__=='__main__':unittest.main()
