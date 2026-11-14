"""Compare final source on synthetic inputs; never import old credential modules."""
import argparse,ast,copy,hashlib,json,re,tempfile,threading,textwrap
from pathlib import Path
from types import SimpleNamespace
from skill_optimizer import Task,Execution,Score,Experience,LearningConfig,learn
from skill_optimizer._vendor.skillopt.gradient import reflect
from skill_optimizer._vendor.skillopt.optimizer.skill import apply_patch_with_report
from skill_optimizer._vendor.skillopt.types import RawPatch
from skill_optimizer.research import officeqa
from skill_optimizer.storage import read,dump,sha
from verify_provenance import verify


def main(source_root,output):
    result=verify(Path(__file__).resolve().parents[1],source_root)
    path=source_root/'officeqa-skill-research/oqs/learn.py'
    text=path.read_text(encoding='utf-8');tree=ast.parse(text)
    symbols={'flatten_native','sanitize_card','ReflectionRecoveryError','_CARD_FIELDS','_OPERATIONS','_FUSED_APPEND','_syntax_text','_repair','_validate_card','AuditedReflectionParser'}
    def name(node):
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)):return node.name
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name):return node.targets[0].id
    extracted=ast.Module(body=[n for n in tree.body if name(n) in symbols],type_ignores=[])
    ns=dict(copy=copy,hashlib=hashlib,json=json,re=re,threading=threading,Path=Path,dump=dump,sha=sha)
    exec(compile(extracted,str(path),'exec'),ns)
    rows=[dict(id='m1',timestamp='01',message=dict(role='assistant',content=[dict(type='toolCall',name='sum',arguments={'values':[2,3]})])),dict(id='m2',timestamp='02',message=dict(role='toolResult',content='5'))]
    assert ns['flatten_native'](rows+[rows[0]])==officeqa.flatten_native(rows+[rows[0]])
    for body in ['Keep units consistent.','UID123 in treasury_bulletin 2025.','x'*3501]:
        card=dict(title='Check evidence',trigger=['total'],body=body,required_operations=['sum'])
        assert ns['sanitize_card'](card)==officeqa.sanitize_card(card)
    card=dict(title='Check evidence',trigger=['total'],body='Check units before adding.',required_operations=['sum'])
    response=json.dumps(dict(patch=dict(edits=[dict(op='append',content=json.dumps(card))])))
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp);a=ns['AuditedReflectionParser'](temp/'original-parser',reflect.extract_json);b=officeqa.AuditedReflectionParser(temp/'portable-parser',reflect.extract_json)
        for raw in [response,response.replace('}]}}','},]}}'),json.dumps(dict(patch=dict(edits=[])))]:assert a(raw)==b(raw)
        task=Task('synthetic','Return only the total of 2 and 3.','train',answer='5')
        e=Experience(task,Execution(task.id,'2',rows),Score(0,0,'Synthetic official score=0'))
        seed=dict(version='synthetic',base_skill='Base',cards=[],config=dict(contract=False,routing='topk',topk=6))
        class Model:
            def identity(self):return {'kind':'source-equivalence-synthetic'}
            def __call__(self,**kw):return response,{}
        portable=learn([e],seed,temp/'portable',Model(),officeqa.CARD_SYSTEM,LearningConfig(workers=1))
        patches=read(portable.parent/'raw-patches.json')
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main');main_source=ast.get_source_segment(text,node)
        start=main_source.index("    cards=list(seed['cards']); seen=");end=main_source.index('    bank=dict(seed,',start)
        env=dict(ns,seed=seed,patches=patches,RawPatch=RawPatch,apply_patch_with_report=apply_patch_with_report,args=SimpleNamespace(run='synthetic'),out=temp/'original')
        exec(textwrap.dedent(main_source[start:end]),env)
        def rules(cards):return [{k:v for k,v in c.items() if k!='provenance'} for c in cards]
        assert rules(env['cards'])==rules(read(portable)['cards'])
        src=(source_root/'SkillOpt/skillopt/gradient/reflect.py').read_bytes().replace(b'from skillopt.',b'from skill_optimizer._vendor.skillopt.')
        original={};exec(compile(src,'original-reflect.py','exec'),original)
        captured=[[],[]]
        def model(index):
            def call(system,user,**kwargs):captured[index].append((system,user,kwargs));return response,{}
            return call
        old,old_parser=reflect.chat_optimizer,reflect.extract_json
        original['chat_optimizer']=model(0);original['extract_json']=b
        reflect.chat_optimizer,reflect.extract_json=model(1),b
        results=read(portable.parent/'rollouts.json')
        opts=dict(workers=1,failure_only=False,minibatch_size=5,edit_budget=3,random_seed=20261103,error_system=officeqa.CARD_SYSTEM,success_system=officeqa.CARD_SYSTEM,skill_aware_reflection=False)
        try:
            one=original['run_minibatch_reflect'](results,'Base',str(portable.parent/'predictions'),str(temp/'reference-patches'),**opts)
            two=reflect.run_minibatch_reflect(results,'Base',str(portable.parent/'predictions'),str(temp/'portable-patches'),**opts)
        finally:reflect.chat_optimizer,reflect.extract_json=old,old_parser
        assert captured[0]==captured[1] and one==two
    result.update(synthetic_inputs_only=True,model_calls=0,credential_files_read=False,checks=['all vendored bytes match source after namespace substitution','native flattening and duplicate identities','original instance filters','original audited parser and syntax recovery','original card-update block produces identical rules','original dispatcher has identical model prompts/options and patches'])
    dump(output,result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--source-root',required=True,type=Path);ap.add_argument('--output',type=Path,default=Path('reports/algorithm-equivalence.json'));args=ap.parse_args();main(args.source_root,args.output)
