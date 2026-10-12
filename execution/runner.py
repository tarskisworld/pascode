"""Central, offline pascode validation and execution mapping. No live writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry
sys.path.insert(0,'/app')
from worker import load
from adapters import MappingError,rest_plan

def workflow_control_errors(workflows):
    """Check declared resolution behavior; this does not test live issue behavior."""
    errors=[]
    controls=workflows['controls']
    for name,workflow in workflows['workflow_definitions'].items():
        statuses=workflow['statuses']
        if controls['done_sets_resolution'] and statuses.get(workflow['initial_status'])=='DONE':
            errors.append(f'{name}: initial DONE status requires an unsupported initial resolution effect')
        for transition in workflow['transitions']:
            source=statuses.get(transition['from']);target=statuses.get(transition['to'])
            if source is None or target is None:continue  # Reference validation reports this.
            effects=set(transition['effects']);label=f'{name}: {transition["name"]}'
            if len(effects)>1:errors.append(f'{label}: conflicting resolution effects')
            if controls['done_sets_resolution'] and target=='DONE' and 'set_resolution' not in effects:
                errors.append(f'{label}: transition to DONE must set_resolution')
            if controls['reopen_clears_resolution'] and source=='DONE' and target!='DONE' and 'clear_resolution' not in effects:
                errors.append(f'{label}: reopening from DONE must clear_resolution')
            if 'set_resolution' in effects and target!='DONE':
                errors.append(f'{label}: set_resolution requires a DONE destination')
            if 'clear_resolution' in effects and target=='DONE':
                errors.append(f'{label}: clear_resolution conflicts with a DONE destination')
    return errors

def validate(root):
    family=root/'jira-as-code'
    documents={}
    errors=[]
    for path in sorted((family/'config').glob('*.yaml')):
        try:
            value,_=load(path,root)
            schema,_=load(family/'shapes'/f'{path.stem}.schema.json',root)
            Draft202012Validator.check_schema(schema)
            errors.extend(f'{path.name}: {e.json_path}: {e.message}' for e in Draft202012Validator(schema,format_checker=FormatChecker(),registry=Registry()).iter_errors(value))
            documents[path.stem]=value
        except Exception as exc:
            errors.append(f'{path.name}: invalid input/schema ({type(exc).__name__})')
    for name in {'site','projects','workflow-definitions','service-account-registry'}-documents.keys():
        errors.append(f'{name}: missing contract')
    if errors:return documents,errors
    projects=documents['projects']['projects']; keys=[p['key'] for p in projects]
    if len(keys)!=len(set(keys)):errors.append('duplicate project key')
    workflows=documents['workflow-definitions']; definitions=workflows['workflow_definitions']; schemes=workflows['workflow_schemes']
    for p in projects:
        scheme=schemes.get(p['work_type_scheme'])
        if scheme is None or not set(scheme['overrides'])<=set(p['work_types']):errors.append(f'{p["key"]}: invalid scheme')
        if (p['project_type']=='service_desk')!=(p['template']=='it-service-management'):errors.append(f'{p["key"]}: incompatible template')
    for name,s in schemes.items():
        if not {s['default'],*s['overrides'].values()}<=definitions.keys():errors.append(f'{name}: unknown workflow')
    for name,w in definitions.items():
        states=set(w['statuses']); reached={w['initial_status']}; pairs=set()
        if not reached<=states:errors.append(f'{name}: invalid initial status')
        for e in w['transitions']:
            pair=(e['from'],e['to'])
            if not set(pair)<=states or pair in pairs:errors.append(f'{name}: invalid/duplicate edge')
            pairs.add(pair)
        while True:
            expanded=reached|{e['to'] for e in w['transitions'] if e['from'] in reached}
            if reached==expanded:break
            reached=expanded
        if reached!=states:errors.append(f'{name}: unreachable status')
    errors.extend(workflow_control_errors(workflows))
    permission_contract=documents.get('permission-profiles')
    if permission_contract:
        for p in projects:
            if p['permission_profile'] not in permission_contract['permission_profiles']:
                errors.append(f'{p["key"]}: unknown permission profile')
        for name,profile in permission_contract['permission_profiles'].items():
            if not set(profile['roles']) <= permission_contract['project_roles'].keys():
                errors.append(f'{name}: unknown project role')
    for name,a in documents['service-account-registry']['service_account_registry'].items():
        access=a['project_access']; grants={p for r,ps in access.items() if r!='denied' for p in ps}
        if any(not set(ps)<=set(keys) for ps in access.values()):errors.append(f'{name}: unknown project')
        if grants&set(access.get('denied',[])):errors.append(f'{name}: conflicting grants')
        if a['site']!=documents['site']['site']['base_url']:errors.append(f'{name}: wrong site')
    return documents,errors

def mapping(documents):
    resources=[]
    for p in documents['projects']['projects']:
        resources.append({'id':f'project:{p["key"]}','source':'projects.yaml','executor':'terraform','resource_type':'jira_project','desired':p,'status':'blocked','requires':['existing_resource_inventory','lead_account_id','permission_scheme_id','workflow_binding','verified_provider_auth']})
    resources.append({'id':'work-types','source':'projects.yaml','executor':'terraform','resource_type':'jira_issue_type','status':'mapped','requires':['work_type_metadata','import_existing_work_types','verified_provider_auth']})
    resources.append({'id':'work-type-schemes','source':'projects.yaml','executor':'jira_api','status':'mapped','requires':['instance_bindings'],'reason':'fourplusone/jira 0.1.16 has no issue-type-scheme resource'})
    for name,w in documents['workflow-definitions']['workflow_definitions'].items():
        resources.append({'id':f'workflow:{name}','source':'workflow-definitions.yaml','executor':'jira_api','status':'mapped','desired':w,'requires':['instance_bindings','live_validation']})
    resources.append({'id':'workflow-schemes','source':'workflow-definitions.yaml','executor':'jira_api','status':'mapped','desired':documents['workflow-definitions']['workflow_schemes'],'reason':'fourplusone/jira 0.1.16 has no workflow-scheme resource'})
    for name,a in documents['service-account-registry']['service_account_registry'].items():
        resources.append({'id':f'account:{name}','source':'service-account-registry.yaml','executor':'atlassian_admin','status':'blocked','desired':a,'requires':['supported_account_creation_method','entitlements','observed_account_id','explicit_role_binding']})
    resources.append({'id':'site-policy','source':'site.yaml','executor':'execution_policy','status':'declared','desired':documents['site'],'reason':'policy values are retained; a general execution-policy enforcer is not implemented'})
    if 'permission-profiles' in documents:
        resources.append({'id':'permission-profiles','source':'permission-profiles.yaml','executor':'jira_api','status':'mapped',
                          'desired':documents['permission-profiles'],'implementation':'permission_operations and run_bootstrap',
                          'requires':['native_naming_bindings','privileged_bootstrap_identity']})
    digest=hashlib.sha256(json.dumps(documents,sort_keys=True).encode()).hexdigest()
    controls=documents['workflow-definitions']['controls']
    control_contracts={
        key:{'desired':controls[key],'status':'validated_and_mapped','implementation':'workflow_control_errors and workflow_request','live_issue_behavior_verified':False}
        for key in ('done_sets_resolution','reopen_clears_resolution')}
    control_contracts['blocked_representation']={'desired':controls['blocked_representation'],'status':'unimplemented','requires':['flag_field_and_dependency_link_inventory','project_field_context_and_screen_checks']}
    for key in ('implementation_status','transition_graph_status'):
        control_contracts[key]={'desired':controls[key],'status':'metadata','requires_remote_action':False}
    blockers=['execution context and instance bindings are required','production Terraform state backend is not configured','whole-site coverage extends beyond project configuration','blocked representation prerequisites are not verified','general execution-policy enforcement is incomplete']
    if 'permission-profiles' not in documents:blockers.insert(0,'permission profiles are undefined')
    return {'site':documents['site']['site']['base_url'],'source_digest':digest,'deployable':False,'resources':resources,'blockers':blockers,'control_contracts':control_contracts,'unmapped_control_contracts':{'blocked_representation':controls['blocked_representation']}}

def terraform_configuration(docs, defer_permission_assignment=False):
    """Generate the deployment configuration; observations are separate variables."""
    projects={p['key']:p for p in docs['projects']['projects']}
    work_types=sorted({name for p in projects.values() for name in p['work_types']})
    config = {
        'terraform':{'required_version':'>= 1.5.0, < 2.0.0','required_providers':{'jira':{'source':'fourplusone/jira','version':'0.1.16'}}},
        'provider':{'jira':{'url':'${var.jira_api_base_url}','user':'${var.jira_admin_email}','password':'${var.jira_admin_token}'}},
        'variable':{
            'jira_api_base_url':{'type':'string'},'jira_admin_email':{'type':'string'},'jira_admin_token':{'type':'string','sensitive':True},
            'project_lead_account_ids':{'type':'map(string)'},'permission_scheme_ids':{'type':'map(number)'},'project_template_keys':{'type':'map(string)'},
            'work_type_metadata':{'type':'map(object({description=string,is_subtask=bool}))'},
            'work_type_remote_names':{'type':'map(string)','default':{},'description':'Observed native names for declared work types; reuse without renaming.'}},
        'locals':{'projects':projects,'work_types':work_types},
        'resource':{
            'jira_project':{'projects':{'for_each':'${local.projects}','key':'${each.key}','name':'${each.value.name}',
                'project_type_key':'${each.value.project_type}','project_template_key':'${var.project_template_keys[each.key]}',
                'lead_account_id':'${var.project_lead_account_ids[each.key]}','permission_scheme':'${var.permission_scheme_ids[each.key]}',
                'lifecycle':{'prevent_destroy':True,'ignore_changes':['project_template_key','project_type_key','avatar_id','description','url','assignee_type','category_id','notification_scheme','issue_security_scheme']}}},
            'jira_issue_type':{'work_types':{'for_each':'${toset(local.work_types)}','name':'${lookup(var.work_type_remote_names, each.key, each.key)}',
                'description':'${var.work_type_metadata[each.key].description}','is_subtask':'${var.work_type_metadata[each.key].is_subtask}',
                'lifecycle':{'prevent_destroy':True,'ignore_changes':['avatar_id']}}}}}
    if defer_permission_assignment:
        project = config['resource']['jira_project']['projects']
        project.pop('permission_scheme')
        project['lifecycle']['ignore_changes'].append('permission_scheme')
    return config

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['validate','map'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--bindings',type=Path)
    args=parser.parse_args()
    docs,errors=validate(args.root)
    if errors:print(json.dumps({'valid':False,'errors':errors},indent=2));return 1
    if args.command=='validate':print(json.dumps({'valid':True,'contracts':len(docs)}));return 0
    report=mapping(docs)
    bindings={}
    if args.bindings:
        bindings,_=load(args.bindings,args.bindings.parent)
        schema=json.loads((Path(__file__).parent/'bindings.schema.json').read_text())
        binding_errors=[f'{e.json_path}: {e.message}' for e in Draft202012Validator(schema).iter_errors(bindings)]
        if binding_errors:
            print(json.dumps({'error':'invalid_bindings','errors':binding_errors},indent=2));return 1
    try:
        requests=rest_plan(docs,bindings)
    except MappingError as exc:
        print(json.dumps({'error':'mapping_failed','reason':str(exc)}));return 1
    requests['source_digest']=report['source_digest']
    requests['bindings_digest']=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    report['rest_operations']={'mapped':sum(o['status']=='mapped' for o in requests['operations']),'binding_required':sum(o['status']=='binding_required' for o in requests['operations'])}
    if args.output:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'execution-map.json').write_text(json.dumps(report,indent=2)+'\n')
        config=terraform_configuration(docs)
        (args.output/'projects.tf.json').write_text(json.dumps(config,indent=2)+'\n')
        (args.output/'rest-plan.json').write_text(json.dumps(requests,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
