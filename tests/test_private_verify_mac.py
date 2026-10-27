"""Fictional selected-file workflow checks; no native Mac acceptance is claimed."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'tools/private_verify/mac-main.cjs'
SPEC = importlib.util.spec_from_file_location('device_fixtures', ROOT / 'tests/test_private_device_verifier_node.py')
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)
MARKER = 'FICTIONAL_PRIVATE_FILENAME_AND_CONTENT_MUST_NOT_APPEAR'

RUNNER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises');
const constants=require('node:fs').constants,path=require('node:path'),crypto=require('node:crypto');
const api=require(process.argv[1]);
const q=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
async function rejected(fn,code){await assert.rejects(fn,error=>error.code===code);}
function mapped(stat,owner=501n){return {...stat,uid:owner,isFile:()=>stat.isFile(),
  isDirectory:()=>stat.isDirectory(),isSymbolicLink:()=>stat.isSymbolicLink()};}
function localFs(overrides={}){
  const underlying=overrides.lstat??fs.lstat;
  return {...fs,...overrides,async lstat(filename,options){
    const stat=await underlying(filename,options);
    // This worker maps its container root to nobody. Darwin's / is root-owned;
    // only that environment difference is adapted, never selected-file UID.
    return filename==='/'?mapped(stat,0n):stat;
  }};
}
async function fixtureWorkflow(extra={}){
  const events=[],lines=[];let choice=0,created,restoreCalls=0,readCalls=0;
  const requests=[],plan=extra.plan?[...extra.plan]:null;
  const originals=await Promise.all(q.files.map(filename=>fs.readFile(filename)));
  const fsApi={...fs,
    async lstat(filename,options){events.push({kind:'stat',filename});let st=mapped(await fs.lstat(filename,options));
      if(extra.sizeOverride&&q.files.includes(filename))st.size=BigInt(extra.sizeOverride);
      if(extra.duplicateInode&&filename===q.files[2])st.ino=(await fs.lstat(q.files[1],options)).ino;
      return st;},
    async open(filename,flags,mode){events.push({kind:'open',filename,flags,mode});
      const h=await fs.open(filename,flags,mode);
      return new Proxy(h,{get(target,key){
        if(key==='stat')return async options=>mapped(await target.stat(options));
        if(key==='read')return async options=>{readCalls++;return target.read(options);};
        const value=Reflect.get(target,key);return typeof value==='function'?value.bind(target):value;
      }});
    }};
  const load=filename=>{
    events.push({kind:'load',filename});
    if(filename.endsWith('/app/macos.cjs'))return {async createPrivateDirectory(parent,prefix){
      events.push({kind:'create'});created=await fs.mkdtemp(path.join(parent,prefix));
      await fs.chmod(created,0o700);return created;
    }};
    return require(filename);
  };
  const execFile=async(executable,args,options)=>{
    assert.equal(executable,'/usr/bin/osascript');
    assert.equal(args[0],'-e');assert.equal(args[2],'--');
    assert.equal(options.encoding,'utf8');
    events.push({kind:'choice',index:choice});const call=choice++;
    if(extra.cancelAt===call)return {stdout:'selection-cancelled\n',stderr:''};
    if(extra.nativeFailureAt===call){
      const error=new Error(q.marker+' /PRIVATE/path');
      if(extra.timeout){error.killed=true;error.signal='SIGTERM';}
      throw error;
    }
    if(call===0){assert.equal(args[1],api._scriptsForTests.attest);
      return {stdout:extra.deny?'no\n':'scope-confirmed\n',stderr:''};}
    if(plan){
      const item=plan.shift();assert(item,'unexpected native chooser restart');
      if(item.kind==='duplicate'){
        assert.equal(args[1],api._scriptsForTests.duplicate);
        assert.deepEqual(args.slice(3),[api.INPUT_SLOTS[item.current].prompt,api.INPUT_SLOTS[item.previous].prompt]);
        requests.push({kind:'duplicate',current:item.current,previous:item.previous});
        return {stdout:item.response+'\n',stderr:''};
      }
      assert.equal(item.kind,'choose');assert.equal(args[1],api._scriptsForTests.choose);
      assert.equal(args[3],api.INPUT_SLOTS[item.slot].prompt);
      requests.push({kind:'choose',slot:item.slot});
      return {stdout:q.files[item.file]+'\n',stderr:''};
    }
    assert.equal(args[1],api._scriptsForTests.choose);
    assert.equal(args[3],api.INPUT_SLOTS[call-1].prompt);
    requests.push({kind:'choose',slot:call-1});
    return {stdout:q.files[call-1]+'\n',stderr:''};
  };
  const workflow=api._createWorkflowForTests({fs:fsApi,uid:()=>501,euid:()=>501,platform:'darwin',
    arch:'arm64',execFile,load,log:line=>lines.push(line)});
  const options={oldBundleRoot:q.oldRoot,addonRoot:path.dirname(process.argv[1])};
  if(extra.restore==='passed')options.restore=async input=>{
    restoreCalls++;assert.equal(typeof input.backupJson,'string');
    assert.equal(input.project,api.FIXED_PROJECT);assert.equal(typeof input.household,'string');
    // This is only a mock contract check, never a claimed database restore.
    await input.writePrivateArtifact('mock-contract.json',Buffer.from('{"mock_only":true}'));
    return {outcome:'passed',restore_execution_verified:true};
  };
  if(extra.restore==='failed')options.restore=async()=>{restoreCalls++;throw new Error(q.marker);};
  if(extra.restore==='unverified')options.restore=async()=>({outcome:'passed',restore_execution_verified:false});
  return {workflow,options,events,lines,requests,originals,get remainingPlan(){return plan?.length??0;},
    get created(){return created;},get readCalls(){return readCalls;},
    get restoreCalls(){return restoreCalls;}};
}
(async()=>{
  const mode=q.mode;
  if(mode==='chooser-order'){
    const f=await fixtureWorkflow();
    const result=await f.workflow.main(f.options);
    assert.equal(result,2);assert.equal(f.restoreCalls,0);
    const choices=f.events.map((e,i)=>e.kind==='choice'?i:-1).filter(i=>i>=0);
    assert.equal(choices.length,8);
    const firstStat=f.events.findIndex(e=>e.kind==='stat'||e.kind==='open'||e.kind==='create');
    assert(firstStat>choices.at(-1));
    const report=JSON.parse(await fs.readFile(path.join(f.created,'verification-report.json'),'utf8'));
    assert.equal(report.restore_execution_verified,false);assert.equal(report.release_authorized,false);
    assert.equal(report.outcome,'review_required');assert(report.issues.includes('local-restore-not-ready'));
    assert.equal(report.source_files.length,7);
    for(let i=0;i<q.files.length;i++){
      const name=api.INPUT_SLOTS[i].slot+(i===0?'.bin':'.json');
      const source=await fs.readFile(q.files[i]),copied=await fs.readFile(path.join(f.created,name));
      assert.equal(hash(copied),hash(source));
      assert.equal((await fs.stat(path.join(f.created,name))).mode&0o777,0o600);
      assert.equal(report.source_files[i].sha256,hash(source));
    }
    assert(f.lines.every(line=>!line.includes(q.marker)&&!line.includes(q.oldRoot)));
    assert(f.lines.some(line=>line==='Коды: local-restore-not-ready'));
    assert.deepEqual(f.lines.filter(line=>line.startsWith('Выбран файл ')),
      api.INPUT_SLOTS.map((slot,index)=>`Выбран файл ${index+1} из 7: ${slot.label}.`));
    assert(api.INPUT_SLOTS.every((slot,index)=>slot.prompt.startsWith(`Файл ${index+1} из 7. `)));
  }else if(mode==='cancel'){
    const f=await fixtureWorkflow({cancelAt:q.cancelAt});
    assert.equal(await f.workflow.main(f.options),1);
    assert.equal(f.events.filter(e=>['stat','open','create'].includes(e.kind)).length,0);
    assert.equal(f.created,undefined);assert(f.lines.includes('Коды: owner-selection-cancelled'));
    assert(f.lines.every(line=>!line.includes(q.marker)));
  }else if(mode==='deny'){
    const f=await fixtureWorkflow({deny:true});
    assert.equal(await f.workflow.main(f.options),1);
    assert.equal(f.events.filter(e=>e.kind==='choice').length,1);
    assert.equal(f.events.filter(e=>['stat','open','create'].includes(e.kind)).length,0);
    assert(f.lines.includes('Коды: owner-scope-not-attested'));
  }else if(mode==='native-failure'){
    const f=await fixtureWorkflow({nativeFailureAt:q.failureAt,timeout:q.timeout});
    assert.equal(await f.workflow.main(f.options),1);
    assert.equal(f.events.filter(e=>['stat','open','create'].includes(e.kind)).length,0);
    assert(f.lines.includes('Коды: '+(q.timeout?'owner-selection-timeout':'owner-selection-failed')));
    assert(!f.lines.includes('Коды: owner-selection-cancelled'));
    assert(f.lines.every(line=>!line.includes(q.marker)));
  }else if(mode==='duplicate-retry'||mode==='duplicate-correct-previous'||mode==='duplicate-finish'){
    const choose=(slot,file=slot)=>({kind:'choose',slot,file});
    const current=mode==='duplicate-correct-previous'?6:2,previous=1;
    const recovery={kind:'duplicate',current,previous,response:
      mode==='duplicate-retry'?'choose-current':mode==='duplicate-correct-previous'?'correct-previous':'selection-cancelled'};
    const plan=mode==='duplicate-correct-previous'?
      [choose(0),choose(1,6),...Array.from({length:5},(_,i)=>choose(i+2)),recovery,choose(1),choose(6)]:
      [choose(0),choose(1),choose(2,1),recovery,...(mode==='duplicate-finish'?[]:
        Array.from({length:5},(_,i)=>choose(i+2)))];
    const f=await fixtureWorkflow({plan});
    const status=await f.workflow.main(f.options);
    assert.equal(f.remainingPlan,0);
    assert.equal(f.requests.filter(item=>item.kind==='duplicate').length,1);
    if(mode==='duplicate-finish'){
      assert.equal(status,1);assert.equal(f.created,undefined);assert.equal(f.readCalls,0);
      assert.equal(f.events.filter(e=>['stat','open','create'].includes(e.kind)).length,0);
      assert(f.lines.includes('Коды: owner-selection-cancelled'));
    }else{
      assert.equal(status,2);
      const indexes=f.requests.filter(item=>item.kind==='choose').map(item=>item.slot);
      assert.deepEqual(indexes,mode==='duplicate-retry'?[0,1,2,2,3,4,5,6]:[0,1,2,3,4,5,6,1,6]);
      const lastChoice=f.events.map((event,index)=>event.kind==='choice'?index:-1).filter(i=>i>=0).at(-1);
      assert(f.events.findIndex(e=>['stat','open','create'].includes(e.kind))>lastChoice);
      const report=JSON.parse(await fs.readFile(path.join(f.created,'verification-report.json'),'utf8'));
      assert.equal(report.source_files.length,7);assert.equal(report.release_authorized,false);
      for(let i=0;i<q.files.length;i++){
        assert.equal(hash(await fs.readFile(q.files[i])),hash(f.originals[i]));
        assert.equal(report.source_files[i].sha256,hash(f.originals[i]));
      }
      assert(!f.lines.includes('Коды: duplicate-selected-file'));
    }
    assert(f.lines.every(line=>!line.includes(q.marker)&&!line.includes(q.oldRoot)&&
      q.files.every(filename=>!line.includes(filename))));
  }else if(mode==='duplicate-inode'){
    const f=await fixtureWorkflow({duplicateInode:true});
    assert.equal(await f.workflow.main(f.options),1);assert.equal(f.readCalls,0);
    assert.equal(f.created,undefined);assert(f.lines.includes('Коды: duplicate-selected-file'));
  }else if(mode==='comparison-review'){
    const changed=JSON.parse(await fs.readFile(q.files[5],'utf8'));changed.unknownFutureField={keep:true};
    await fs.writeFile(q.files[5],JSON.stringify(changed));
    const f=await fixtureWorkflow({restore:'passed'});
    assert.equal(await f.workflow.main(f.options),2);
    const report=JSON.parse(await fs.readFile(path.join(f.created,'verification-report.json'),'utf8'));
    assert.equal(report.outcome,'review_required');assert.equal(report.restore_execution_verified,true);
    assert.equal(report.release_authorized,false);assert(report.issues.includes('device-export-diverges'));
    assert.deepEqual(JSON.parse(await fs.readFile(q.files[5],'utf8')),changed);
    assert(f.lines.every(line=>!line.includes(q.marker)));
  }else if(mode==='runtime-gates'){
    for(const settings of [{platform:'linux',uid:501,euid:501},{platform:'darwin',uid:0,euid:0},
      {platform:'darwin',uid:501,euid:502}]){
      const lines=[];
      const workflow=api._createWorkflowForTests({platform:settings.platform,arch:'arm64',
        uid:()=>settings.uid,euid:()=>settings.euid,log:line=>lines.push(line),
        load(){throw Error('must-not-load');},execFile(){throw Error('must-not-select');},
        fs:new Proxy({},{get(){throw Error('must-not-read');}})});
      assert.equal(await workflow.main({oldBundleRoot:q.oldRoot,addonRoot:path.dirname(process.argv[1])}),1);
      assert.deepEqual(lines,['Результат: failed','Коды: unsupported-owner-runtime']);
    }
  }else if(mode==='total-limit'){
    const f=await fixtureWorkflow({sizeOverride:20*1024*1024});
    assert.equal(await f.workflow.main(f.options),1);
    assert.equal(f.readCalls,0);assert.equal(f.created,undefined);
    assert(f.lines.includes('Коды: input-total-size-limit'));
  }else if(mode==='restore-contract'){
    const f=await fixtureWorkflow({restore:q.restore});
    const result=await f.workflow.main(f.options);
    assert.equal(result,q.restore==='passed'?0:1);
    const report=JSON.parse(await fs.readFile(path.join(f.created,q.restore==='passed'?
      'verification-report.json':'verification-failure.json'),'utf8'));
    assert.equal(report.restore_execution_verified,q.restore==='passed');
    assert.equal(report.release_authorized,false);
    if(q.restore==='passed'){
      assert.equal(report.outcome,'passed');assert.equal(f.restoreCalls,1);
      assert.equal(JSON.parse(await fs.readFile(path.join(f.created,'mock-contract.json'),'utf8')).mock_only,true);
    }else{
      assert.equal(report.outcome,'failed');
      assert(report.issues.includes(q.restore==='failed'?'local-restore-failed':'local-restore-unverified'));
    }
    assert(f.lines.every(line=>!line.includes(q.marker)&&!line.includes(q.oldRoot)));
  }else if(mode==='read-guards'){
    const workflow=api._createWorkflowForTests({fs:localFs()}),owner=BigInt(process.getuid());
    const filename=q.files[1],before=await fs.readFile(filename);
    const proof=await workflow.inspectInput(filename,owner);
    const bytes=await workflow.readInput(proof);assert.equal(hash(bytes),hash(before));
    await fs.appendFile(filename,' ');
    await rejected(()=>workflow.readInput(proof),'input-file-changed');
    await fs.writeFile(filename,before);
    const symlink=path.join(q.oldRoot,'link.json');await fs.symlink(filename,symlink);
    await rejected(()=>workflow.inspectInput(symlink,owner),'input-path-unsafe');
    const parentLink=path.join(q.oldRoot,'linked');await fs.symlink(path.dirname(filename),parentLink);
    await rejected(()=>workflow.inspectInput(path.join(parentLink,path.basename(filename)),owner),'input-path-unsafe');
    const hardlink=path.join(q.oldRoot,'hard.json');await fs.link(filename,hardlink);
    await rejected(()=>workflow.inspectInput(filename,owner),'input-file-invalid');
    await rejected(()=>workflow.inspectInput(hardlink,owner),'input-file-invalid');
    await fs.unlink(hardlink);
    const empty=path.join(q.oldRoot,'empty.json');await fs.writeFile(empty,'');
    await rejected(()=>workflow.inspectInput(empty,owner),'input-file-size-limit');
    const huge=path.join(q.oldRoot,'huge.json'),h=await fs.open(huge,'wx',0o600);
    await h.truncate(api.MAX_FILE+1);await h.close();
    await rejected(()=>workflow.inspectInput(huge,owner),'input-file-size-limit');
    await rejected(()=>workflow.inspectInput(q.oldRoot,owner),'input-file-invalid');
    const foreignFs=localFs({async lstat(name,options){
      const stat=await fs.lstat(name,options);return name===filename?mapped(stat,owner+1n):stat;
    }});
    await rejected(()=>api._createWorkflowForTests({fs:foreignFs}).inspectInput(filename,owner),'input-file-invalid');
    const unsafeDir=path.join(q.oldRoot,'shared');await fs.mkdir(unsafeDir,{mode:0o777});await fs.chmod(unsafeDir,0o777);
    await fs.writeFile(path.join(unsafeDir,'file.json'),'{}');
    await rejected(()=>workflow.inspectInput(path.join(unsafeDir,'file.json'),owner),'input-path-unsafe');
  }else if(mode==='open-race'){
    const owner=BigInt(process.getuid()),filename=q.files[1],events=[];
    let replacement=false;
    const fsApi={...fs,async open(name,flags,permissions){
      assert.equal(flags,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
      if(name===filename&&!replacement){
        replacement=true;await fs.rename(name,name+'.old');await fs.writeFile(name,'{}');
      }
      return fs.open(name,flags,permissions);
    }};
    const workflow=api._createWorkflowForTests({fs:localFs(fsApi)});
    const proof=await workflow.inspectInput(filename,owner);
    await rejected(()=>workflow.readInput(proof),'input-file-changed');
  }else if(mode==='read-growth'){
    const owner=BigInt(process.getuid()),filename=q.files[1];let changed=false;
    const fsApi={...fs,async open(name,flags,permissions){
      const h=await fs.open(name,flags,permissions);
      return new Proxy(h,{get(target,key){
        if(key==='read')return async options=>{
          const result=await target.read(options);
          if(name===filename&&!changed){changed=true;await fs.appendFile(name,' ');}
          return result;
        };
        const value=Reflect.get(target,key);return typeof value==='function'?value.bind(target):value;
      }});
    }};
    const workflow=api._createWorkflowForTests({fs:localFs(fsApi)}),proof=await workflow.inspectInput(filename,owner);
    await rejected(()=>workflow.readInput(proof),'input-file-changed');
  }else if(mode==='close-failure'){
    const owner=BigInt(process.getuid()),filename=q.files[1];
    const fsApi=localFs({async open(name,flags,permissions){
      const h=await fs.open(name,flags,permissions);
      return new Proxy(h,{get(target,key){
        if(key==='close')return async()=>{await target.close();throw new Error(q.marker);};
        const value=Reflect.get(target,key);return typeof value==='function'?value.bind(target):value;
      }});
    }});
    const workflow=api._createWorkflowForTests({fs:fsApi}),proof=await workflow.inspectInput(filename,owner);
    await rejected(()=>workflow.readInput(proof),'input-file-close-failed');
  }else if(mode==='write-guards'){
    const workflow=api._createWorkflowForTests({fs:localFs()}),owner=BigInt(process.getuid());
    const out=path.join(q.oldRoot,'private-out');await fs.mkdir(out,{mode:0o700});
    await workflow.writePrivate(out,'sample.json',Buffer.from('{"exact":9007199254740993}'),owner);
    assert.equal((await fs.stat(path.join(out,'sample.json'))).mode&0o777,0o600);
    await rejected(()=>workflow.writePrivate(out,'sample.json',Buffer.from('replacement'),owner),'private-output-failed');
    await rejected(()=>workflow.writePrivate(out,'../escape.json',Buffer.from('{}'),owner),'private-output-failed');
    await rejected(()=>workflow.writePrivate(out,'empty.json',Buffer.alloc(0),owner),'private-output-failed');
    await rejected(()=>workflow.writePrivate(out,'large.json',Buffer.alloc(api.MAX_FILE+1),owner),'private-output-failed');
    await workflow.writePrivate(out,'server-restored-PRIVATE.json',Buffer.from('{"mock_only":true}'),owner);
    assert.equal(await fs.readFile(path.join(out,'sample.json'),'utf8'),'{"exact":9007199254740993}');
  }else if(mode==='write-close-race'){
    const owner=BigInt(process.getuid()),out=path.join(q.oldRoot,'private-out-'+q.change);
    await fs.mkdir(out,{mode:0o700});
    const fsApi=localFs({async open(name,flags,permissions){
      const h=await fs.open(name,flags,permissions);
      return new Proxy(h,{get(target,key){
        if(key==='close')return async()=>{
          await target.close();
          if(q.change==='mode')await fs.chmod(name,0o644);
          else{const bytes=await fs.readFile(name);await fs.rename(name,name+'.old');await fs.writeFile(name,bytes,{mode:0o600});}
        };
        const value=Reflect.get(target,key);return typeof value==='function'?value.bind(target):value;
      }});
    }});
    const workflow=api._createWorkflowForTests({fs:fsApi});
    await rejected(()=>workflow.writePrivate(out,'sample.json',Buffer.from('{"keep":true}'),owner),'private-output-changed');
  }else if(mode==='bad-paths'){
    for(const value of ['relative.json','//host/share.json','/a/../b.json','/a//b.json','/a/./b.json',
      '/a/b.json\n','/a/b\u0000.json','/a/','/','/'+('a'.repeat(256))]){
      assert.throws(()=>api._normalizedFileForTests(value,path),error=>error.code==='input-path-unsafe');
    }
    assert.equal(api._normalizedFileForTests('/private/$(not-executed); name.json',path),
      '/private/$(not-executed); name.json');
  }else throw Error('unknown-test-mode');
  process.stdout.write(JSON.stringify({outcome:'passed',case:mode,native_mac_tested:false}));
})().catch(()=>{process.stderr.write('fictional-workflow-test-failed\n');process.exitCode=1;});
"""


class MacPrivateVerificationWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('Node is required')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.fictional-mac-verifier-', dir=ROOT)
        self.root = Path(self.tmp.name)
        self.old = self.root / 'old-helper'
        self.old.mkdir(mode=0o700)
        inputs = self.root / 'selected'
        inputs.mkdir(mode=0o700)
        state = FIX.state()
        raw = FIX.dump(state)
        server = FIX.snapshot(raw)
        server['project_ref'] = 'kqndxecziamypdjpxhyq'
        capture = FIX.captured({'marichevy_state_v10': raw})
        self.files = []
        values = [server, state, capture, state, capture, state, capture]
        for index, value in enumerate(values):
            filename = inputs / f'{MARKER}-{index}.json'
            filename.write_text(FIX.dump(value), encoding='utf8')
            filename.chmod(0o600)
            self.files.append(str(filename))

    def tearDown(self):
        self.tmp.cleanup()

    def run_case(self, mode, **extra):
        request = {'mode': mode, 'oldRoot': str(self.old), 'files': self.files, 'marker': MARKER, **extra}
        env = os.environ.copy()
        env.pop('NODE_OPTIONS', None)
        env.pop('NODE_PATH', None)
        result = subprocess.run([self.node, '--no-global-search-paths', '-e', RUNNER, str(ENTRY)],
                                input=json.dumps(request), text=True, capture_output=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertNotIn(MARKER, result.stdout)
        self.assertEqual(json.loads(result.stdout), {'outcome': 'passed', 'case': mode, 'native_mac_tested': False})

    def test_unconfigured_entry_is_inert_without_native_or_file_module_imports(self):
        script = r"""
const assert=require('node:assert/strict'),Module=require('node:module'),original=Module._load;
Module._load=function(name,parent,isMain){
  if(name.startsWith('node:')||name==='fs'||name==='child_process'||name==='koffi')
    throw Error('unexpected-runtime-access');
  return original.call(this,name,parent,isMain);
};
const api=require(process.argv[1]),lines=[];console.log=line=>lines.push(line);
(async()=>{
  assert.equal(await api.main(),1);
  assert.deepEqual(lines,['Результат: failed','Коды: verified-launch-required']);
  assert.equal(api.INPUT_SLOTS.length,7);assert(Object.isFrozen(api.INPUT_SLOTS));
  process.stdout.write('{"outcome":"inert"}');
})().catch(()=>{process.exitCode=1;});
"""
        result = subprocess.run([self.node, '-e', script, str(ENTRY)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'outcome': 'inert'})

    def test_all_selections_precede_reads_private_byte_copies_and_restore_required(self):
        self.run_case('chooser-order')

    def test_cancellation_never_reads_any_selected_file(self):
        for at in (0, 1, 4, 7):
            with self.subTest(at=at):
                self.run_case('cancel', cancelAt=at)

    def test_owner_scope_confirmation_is_required(self):
        self.run_case('deny')

    def test_duplicate_current_selection_retries_without_restarting_previous_slots(self):
        self.run_case('duplicate-retry')

    def test_duplicate_can_correct_previous_slot_then_return_to_first_missing(self):
        self.run_case('duplicate-correct-previous')

    def test_finishing_duplicate_recovery_never_reads_selected_files(self):
        self.run_case('duplicate-finish')

    def test_native_failure_and_timeout_are_not_reported_as_owner_cancellation(self):
        for failure_at in (0, 1, 4):
            for timeout in (False, True):
                with self.subTest(failure_at=failure_at, timeout=timeout):
                    self.run_case('native-failure', failureAt=failure_at, timeout=timeout)

    def test_distinct_selected_names_cannot_reuse_one_inode(self):
        self.run_case('duplicate-inode')

    def test_unknown_export_difference_remains_review_after_mock_restore(self):
        self.run_case('comparison-review')

    def test_platform_root_and_effective_user_gates_precede_imports_and_reads(self):
        self.run_case('runtime-gates')

    def test_combined_size_guard_stops_before_body_reads(self):
        self.run_case('total-limit')

    def test_mock_restore_hook_contract_is_separate_and_never_authorizes_release(self):
        for result in ('passed', 'failed', 'unverified'):
            with self.subTest(result=result):
                self.run_case('restore-contract', restore=result)

    def test_source_identity_links_owner_file_kind_sizes_and_parent_permissions(self):
        self.run_case('read-guards')

    def test_file_replacement_between_inspection_and_open_is_rejected(self):
        self.run_case('open-race')

    def test_file_growth_during_read_is_rejected(self):
        self.run_case('read-growth')

    def test_read_close_failure_is_not_treated_as_success(self):
        self.run_case('close-failure')

    def test_private_copies_are_exact_owner_only_and_never_overwritten(self):
        self.run_case('write-guards')

    def test_private_output_close_cannot_widen_mode_or_replace_same_bytes(self):
        for change in ('mode', 'inode'):
            with self.subTest(change=change):
                self.run_case('write-close-race', change=change)

    def test_only_canonical_absolute_paths_no_shell_interpolation(self):
        self.run_case('bad-paths')


if __name__ == '__main__':
    unittest.main()

