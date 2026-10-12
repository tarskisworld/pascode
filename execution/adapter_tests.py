import copy,json,unittest
from adapters import MappingError,workflow_request,work_type_scheme_request,workflow_scheme_request,scheme_association

def definition(names=('Queue','Active','Complete')):
    a,b,c=names
    return {'initial_status':a,'statuses':{a:'TODO',b:'IN_PROGRESS',c:'DONE'},
            'transitions':[{'name':'Start','from':a,'to':b,'actor':'contributor','validators':[],'effects':[]},
                           {'name':'Finish','from':b,'to':c,'actor':'contributor','validators':[],'effects':['set_resolution']},
                           {'name':'Reopen','from':c,'to':a,'actor':'contributor','validators':[],'effects':['clear_resolution']}]}

class AdapterTests(unittest.TestCase):
    def test_same_adapter_different_instance_values(self):
        for names,resolution in [(('Queue','Active','Complete'),'100'),(('Inbox','Doing','Finished'),'900')]:
            r=workflow_request(definition(names),{'name':names[0]+'-workflow'},{},{names[2]:resolution})
            self.assertEqual(r['path'],'/rest/api/3/workflows/create')
            ts=r['body']['workflows'][0]['transitions']
            self.assertEqual(len(ts),4)
            self.assertEqual(ts[2]['actions'][0]['parameters']['value'],resolution)
            self.assertEqual(ts[3]['actions'][0]['parameters']['value'],'')
            self.assertFalse(any(t.get('conditions') for t in ts))
    def test_reuse_status_and_reject_category_drift(self):
        r=workflow_request(definition(),{'name':'example'},{'Active':{'id':'17','category':'IN_PROGRESS'}},{'Complete':'100'})
        self.assertEqual(r['body']['statuses'][1]['id'],'17')
        with self.assertRaises(MappingError):workflow_request(definition(),{'name':'example'},{'Active':{'id':'17','category':'DONE'}},{'Complete':'100'})
    def test_never_drop_unknown_rules(self):
        for field,value in [('validators',['unknown']),('effects',['unknown']),('actor','human')]:
            d=definition();d['transitions'][0][field]=value
            with self.assertRaises(MappingError):workflow_request(d,{'name':'example'},{},{'Complete':'100'})
    def test_resolution_binding_required(self):
        with self.assertRaises(MappingError):workflow_request(definition(),{'name':'example'},{},{})
    def test_update_preserves_ids_and_version(self):
        ids={json.dumps(['INITIAL']):'7',json.dumps(['Start','Queue','Active']):'19',json.dumps(['Finish','Active','Complete']):'21',json.dumps(['Reopen','Complete','Queue']):'23'}
        binding={'name':'example','existing':{'id':'workflow-id','version':{'id':'v','versionNumber':3},'transition_ids':ids}}
        statuses={n:{'id':str(i+10),'category':category} for i,(n,category) in enumerate(definition()['statuses'].items())}
        r=workflow_request(definition(),binding,statuses,{'Complete':'100'})
        self.assertEqual(r['path'],'/rest/api/3/workflows/update')
        self.assertEqual(r['body']['workflows'][0]['version'],binding['existing']['version'])
        self.assertEqual([t['id'] for t in r['body']['workflows'][0]['transitions']],['7','19','21','23'])
    def test_update_refuses_unobserved_status(self):
        b={'name':'example','existing':{'id':'w','version':{'id':'v','versionNumber':1},'transition_ids':{json.dumps(['INITIAL']):'1',json.dumps(['Start','Queue','Active']):'2',json.dumps(['Finish','Active','Complete']):'3',json.dumps(['Reopen','Complete','Queue']):'4'}}}
        with self.assertRaises(MappingError):workflow_request(definition(),b,{}, {'Complete':'1'})
    def test_ordered_work_type_members_and_default(self):
        types={'Task':{'id':'11','is_subtask':False},'Child':{'id':'12','is_subtask':True}}
        r=work_type_scheme_request(['Task','Child'],{'name':'types','default_work_type':'Task'},types)
        self.assertEqual(r['body']['issueTypeIds'],['11','12'])
        with self.assertRaises(MappingError):work_type_scheme_request(['Child'],{'name':'types','default_work_type':'Child'},types)
        with self.assertRaises(MappingError):work_type_scheme_request(['Task','Child'],{'name':'types','default_work_type':'Child'},types)
    def test_workflow_scheme_uses_names_and_issue_type_ids(self):
        r=workflow_scheme_request({'default':'delivery','overrides':{'Decision':'decision'}},{'name':'scheme'},{'Decision':{'id':'33','is_subtask':False}},{'delivery':{'name':'site-delivery'},'decision':{'name':'site-decision'}})
        self.assertEqual(r['body']['defaultWorkflow'],'site-delivery')
        self.assertEqual(r['body']['issueTypeMappings'],{'33':'site-decision'})
    def test_missing_bindings_refuse_default_scheme_fallback(self):
        with self.assertRaises(MappingError):workflow_scheme_request({'default':'delivery','overrides':{}},{'name':'scheme'},{},{})
        with self.assertRaises(MappingError):scheme_association('workflow','22',None)
    def test_existing_schemes_are_not_recreated(self):
        with self.assertRaises(MappingError):work_type_scheme_request(['Task'],{'id':'1','name':'existing','default_work_type':'Task'},{'Task':{'id':'2','is_subtask':False}})
        with self.assertRaises(MappingError):workflow_scheme_request({'default':'delivery','overrides':{}},{'id':'1','name':'existing'},{},{'delivery':{'name':'delivery'}})
    def test_scheme_associations_have_distinct_payloads(self):
        self.assertEqual(scheme_association('workflow','22','31')['body'],{'projectId':'22','workflowSchemeId':'31'})
        self.assertEqual(scheme_association('work_type','22','32')['body'],{'projectId':'22','issueTypeSchemeId':'32'})

if __name__=='__main__':unittest.main()
