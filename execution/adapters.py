"""Offline Jira payload adapters. Bindings contain names/IDs, never credentials."""
import json
from uuid import NAMESPACE_URL, uuid5

class MappingError(ValueError):
    pass

def required(mapping,key):
    value=mapping.get(key)
    if value is None or value=='':
        raise MappingError(f'missing binding: {key}')
    return value

def workflow_request(definition,binding,statuses,resolutions):
    """Map a direct company-managed workflow; optional observed update bindings."""
    name=required(binding,'name')
    refs={n:str(uuid5(NAMESPACE_URL,f'pascode:jira:status:{n}')) for n in definition['statuses']}
    status_payload=[]
    for n,category in definition['statuses'].items():
        observed=statuses.get(n)
        item={'name':n,'statusCategory':category,'statusReference':refs[n]}
        if observed:
            if observed.get('category')!=category:
                raise MappingError(f'status category conflict: {n}')
            item['id']=str(required(observed,'id'))
        status_payload.append(item)
    existing=binding.get('existing')
    used=set()
    def transition_id(signature):
        if existing:
            value=str(required(required(existing,'transition_ids'),json.dumps(signature)))
        else:
            value=str(len(used)+1)
        if value in used:raise MappingError(f'duplicate transition ID: {value}')
        used.add(value)
        return value
    transitions=[{'id':transition_id(['INITIAL']),'name':'Create','type':'INITIAL',
                  'toStatusReference':refs[definition['initial_status']],
                  'links':[],'actions':[],'validators':[],'triggers':[],'properties':{}}]
    for t in definition['transitions']:
        if t['actor']!='contributor' or t['validators']:
            raise MappingError('unsupported actor or validator; no rules may be silently dropped')
        if t['from'] not in refs or t['to'] not in refs:
            raise MappingError('unknown transition status')
        if len(t['effects'])!=len(set(t['effects'])) or not set(t['effects'])<={'set_resolution','clear_resolution'}:
            raise MappingError('unsupported or duplicate effect')
        if len(t['effects'])>1:raise MappingError('conflicting resolution effects')
        actions=[]
        if t['effects']:
            value=str(required(resolutions,t['to'])) if t['effects'][0]=='set_resolution' else ''
            actions=[{'ruleKey':'system:update-field','parameters':{'field':'resolution','value':value,'mode':'replace'}}]
        transitions.append({'id':transition_id([t['name'],t['from'],t['to']]),
                            'name':t['name'],'type':'DIRECTED','links':[{'fromStatusReference':refs[t['from']],'fromPort':0,'toPort':1}],
                            'toStatusReference':refs[t['to']],'conditions':None,'actions':actions,'validators':[],
                            'triggers':[],'properties':{}})
    workflow={'description':binding.get('description',''),'statuses':[{'statusReference':refs[n],'properties':{}} for n in refs],
              'transitions':transitions}
    payload={'statuses':status_payload,'workflows':[workflow]}
    if existing:
        if any('id' not in s for s in status_payload):
            raise MappingError('update requires observed IDs for all statuses; status migration is not supported')
        workflow.update(id=required(existing,'id'),version=required(existing,'version'))
        path='/rest/api/3/workflows/update'
    else:
        workflow['name']=name
        payload['scope']={'type':'GLOBAL'}
        path='/rest/api/3/workflows/create'
    return {'method':'POST','path':path,'body':payload,
            'validation':{'method':'POST','path':path+'/validation',
                          'body':{'payload':payload,'validationOptions':{'levels':['ERROR','WARNING']}}}}

def work_type_scheme_request(work_types,binding,issue_types):
    if binding.get('id'):raise MappingError('existing work-type scheme requires reconciliation; duplicate creation forbidden')
    if len(work_types)!=len(set(work_types)):raise MappingError('duplicate work type')
    default=required(binding,'default_work_type')
    if default not in work_types:raise MappingError('default work type is not a scheme member')
    observed=[required(issue_types,n) for n in work_types]
    if not any(not required(o,'is_subtask') for o in observed):
        raise MappingError('a scheme needs a standard work type')
    ids=[str(required(o,'id')) for o in observed]
    if len(ids)!=len(set(ids)):raise MappingError('duplicate bound work-type IDs')
    if issue_types[default]['is_subtask']:raise MappingError('default work type cannot be a subtask')
    return {'method':'POST','path':'/rest/api/3/issuetypescheme',
            'body':{'name':required(binding,'name'),'description':binding.get('description',''),
                    'issueTypeIds':ids,'defaultIssueTypeId':str(issue_types[default]['id'])}}

def workflow_scheme_request(definition,binding,issue_types,workflows):
    if binding.get('id'):raise MappingError('existing workflow scheme requires reconciliation; duplicate creation forbidden')
    ids=[str(required(required(issue_types,n),'id')) for n in definition['overrides']]
    if len(ids)!=len(set(ids)):raise MappingError('duplicate bound work-type IDs')
    return {'method':'POST','path':'/rest/api/3/workflowscheme',
            'body':{'name':required(binding,'name'),'description':binding.get('description',''),
                    'defaultWorkflow':required(required(workflows,definition['default']),'name'),
                    'issueTypeMappings':{str(issue_types[n]['id']):required(required(workflows,w),'name') for n,w in definition['overrides'].items()}}}

def scheme_association(kind,project_id,scheme_id):
    fields={'workflow':'workflowSchemeId','work_type':'issueTypeSchemeId'}
    if kind not in fields or not project_id or not scheme_id:raise MappingError('invalid scheme association')
    path='/rest/api/3/workflowscheme/project' if kind=='workflow' else '/rest/api/3/issuetypescheme/project'
    return {'method':'PUT','path':path,'body':{'projectId':str(project_id),fields[kind]:str(scheme_id)}}

def rest_plan(documents,bindings):
    operations=[]
    def add(identifier,build,dependencies=()):
        try:
            request=build()
            operations.append({'id':identifier,'status':'mapped','request':request,'depends_on':list(dependencies)})
        except MappingError as exc:
            operations.append({'id':identifier,'status':'binding_required','reason':str(exc),'depends_on':list(dependencies)})
    workflows=documents['workflow-definitions']
    for name,definition in workflows['workflow_definitions'].items():
        add('workflow:'+name,lambda n=name,d=definition:workflow_request(d,bindings.get('workflows',{}).get(n,{}),bindings.get('statuses',{}),bindings.get('resolutions',{})))
    groups={}
    for p in documents['projects']['projects']:
        name=p['work_type_scheme']
        if name in groups and groups[name]!=p['work_types']:raise MappingError('inconsistent shared work-type scheme membership')
        groups[name]=p['work_types']
    for name,members in groups.items():
        add('work-type-scheme:'+name,lambda n=name,m=members:work_type_scheme_request(m,bindings.get('work_type_schemes',{}).get(n,{}),bindings.get('issue_types',{})),['work-types'])
    for name,definition in workflows['workflow_schemes'].items():
        add('workflow-scheme:'+name,lambda n=name,d=definition:workflow_scheme_request(d,bindings.get('workflow_schemes',{}).get(n,{}),bindings.get('issue_types',{}),bindings.get('workflows',{})),['workflow:'+w for w in sorted({definition['default'],*definition['overrides'].values()})])
    for project in documents['projects']['projects']:
        for kind,key in [('workflow','workflow_schemes'),('work_type','work_type_schemes')]:
            def build(p=project,k=kind,b=key):
                return scheme_association(k,required(bindings.get('projects',{}),p['key']),required(bindings.get(b,{}).get(p['work_type_scheme'],{}),'id'))
            add(f'{kind}-association:{project["key"]}',build,[f'project:{project["key"]}',f'{"workflow" if kind=="workflow" else "work-type"}-scheme:{project["work_type_scheme"]}'])
    return {'format_version':1,'live_execution':False,'operations':operations}
