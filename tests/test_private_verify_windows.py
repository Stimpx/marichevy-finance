"""Windows workflow with fictional files and substituted native UI/IO only.

Shared strict comparison/decoder and actual private copies are exercised. These
checks do not claim native Windows dialogs, DACLs or a database restore.
"""
import importlib.util
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'tools/private_verify/windows-main.cjs'
SPEC = importlib.util.spec_from_file_location('device_fixtures', ROOT / 'tests/test_private_device_verifier_node.py')
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)
MARKER = 'FICTIONAL_WINDOWS_PRIVATE_PATH_AND_HISTORY_MUST_NOT_APPEAR'
INTEGRATION_SPEC = importlib.util.spec_from_file_location('private_integration_fixtures', ROOT / 'tests/test_private_verification_integration.py')
INTEGRATION = importlib.util.module_from_spec(INTEGRATION_SPEC)
INTEGRATION_SPEC.loader.exec_module(INTEGRATION)

RUNNER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises');
const path=require('node:path'),crypto=require('node:crypto');
const api=require(process.argv[1]),q=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const logical=q.files.map((_,index)=>'C:\\Fictional Owner\\'+q.marker+'-'+index+'.json');
async function fixture(extra={}){
  const events=[],lines=[],requests=[],writes=[];let choice=0,created,restoreCalls=0;
  const originals=await Promise.all(q.files.map(filename=>fs.readFile(filename)));
  const plan=extra.plan?[...extra.plan]:null;
  function indexOf(filename){const index=logical.findIndex(value=>value.toLowerCase()===filename.toLowerCase());assert(index>=0);return index;}
  function safeIOError(code){const error=new Error(q.marker);error.name='WindowsIOError';error.code=code;return error;}
  const io={
    assertPlatform(){events.push({kind:'platform'});},
    getSystemDirectory(){return 'C:\\Windows\\System32';},
    inspectInput(filename,limit){
      const index=indexOf(filename);events.push({kind:'inspect',index});assert.equal(limit,api.MAX_FILE);
      if(extra.ioError)throw safeIOError(extra.ioError);
      return {filename,stat:{size:BigInt(extra.sizeOverride??originals[index].length)},
        identity:'fictional-'+index,inode:'fictional-file-'+(extra.duplicateInode&&index===2?1:index)};
    },
    readInput(proof){
      const index=indexOf(proof.filename);events.push({kind:'read',index});
      return extra.shortRead&&index===1?Buffer.alloc(1):Buffer.from(originals[index]);
    },
    unchangedInput(proof){events.push({kind:'unchanged',index:indexOf(proof.filename)});
      if(extra.changed)throw safeIOError('input-file-changed');},
    async createPrivateDirectory(parent,prefix){
      events.push({kind:'create'});assert.equal(parent,path.dirname(path.dirname(process.argv[1])));
      assert.equal(prefix,'PRIVATE-verification-');
      created=await fs.mkdtemp(path.join(q.outRoot,prefix));await fs.chmod(created,0o700);return created;
    },
    verifyPrivateDirectory(directory){assert.equal(directory,created);return true;},
    async writePrivate(directory,name,bytes){
      assert.equal(directory,created);writes.push(name);
      await fs.writeFile(path.join(directory,name),bytes,{flag:'wx',mode:0o600});
      assert.equal(hash(await fs.readFile(path.join(directory,name))),hash(bytes));
    },
  };
  const execFile=async(executable,args,options)=>{
    assert.equal(executable,'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe');
    assert.deepEqual(args.slice(0,-1),['-NoLogo','-NoProfile','-NonInteractive','-STA','-EncodedCommand']);
    assert.equal(Buffer.from(args.at(-1),'base64').toString('utf16le'),api._uiScriptForTests);
    assert.equal(options.encoding,'utf8');assert.equal(options.windowsHide,true);assert.equal(options.timeout,600000);
    assert.deepEqual(Object.keys(options.env).sort(),['MARICHEVY_VERIFY_REQUEST','SystemRoot','WINDIR']);
    assert.equal(options.env.SystemRoot,'C:\\Windows');assert.equal(options.env.WINDIR,'C:\\Windows');
    const request=JSON.parse(options.env.MARICHEVY_VERIFY_REQUEST);requests.push(request);
    events.push({kind:'choice',request});const call=choice++;
    if(extra.failureAt===call){const error=new Error(q.marker);if(extra.timeout)error.killed=true;throw error;}
    if(extra.malformedAt===call)return {stdout:'not-json '+q.marker,stderr:''};
    if(extra.rawErrorAt===call)return {stdout:'{}',stderr:q.marker};
    if(extra.cancelAt===call)return {stdout:'{"result":"selection-cancelled"}',stderr:''};
    let response;
    if(call===0){assert.deepEqual(request,{mode:'attest'});response={result:extra.deny?'choose-current':'scope-confirmed'};}
    else if(plan){
      const step=plan.shift();assert(step,'unexpected restart');
      if(step.mode==='duplicate'){
        assert.deepEqual(request,{mode:'duplicate',index:step.index,previous:step.previous});
        response={result:step.response};
      }else{
        assert.deepEqual(request,{mode:'choose',index:step.index});
        const selected=step.lowercase?logical[step.file].toLowerCase():logical[step.file];
        response={result:'file',path:Buffer.from(selected,'utf8').toString('base64')};
      }
    }else{
      assert.deepEqual(request,{mode:'choose',index:call-1});
      response={result:'file',path:Buffer.from(logical[call-1],'utf8').toString('base64')};
    }
    return {stdout:JSON.stringify(response)+'\r\n',stderr:''};
  };
  const workflow=api._createWorkflowForTests({platform:'win32',arch:'x64',io,execFile,log:line=>lines.push(line)});
  const options={addonRoot:path.dirname(process.argv[1]),bundleRoot:path.dirname(path.dirname(process.argv[1]))};
  if(extra.restore==='passed')options.restore=async input=>{
    restoreCalls++;assert.equal(typeof input.backupJson,'string');assert.equal(input.project,api.FIXED_PROJECT);
    // Deliberately a mock contract, not a claimed PostgreSQL restoration.
    await input.writePrivateArtifact('mock-contract.json',Buffer.from('{"mock_only":true}'));
    return {outcome:'passed',restore_execution_verified:true};
  };
  if(extra.restore==='failed')options.restore=async()=>{restoreCalls++;throw new Error(q.marker);};
  if(extra.restore==='unverified')options.restore=async()=>({outcome:'passed',restore_execution_verified:false});
  return {workflow,options,events,lines,requests,writes,originals,get remaining(){return plan?.length??0;},
    get created(){return created;},get restoreCalls(){return restoreCalls;}};
}
function privateEvents(f){return f.events.filter(event=>['inspect','read','unchanged','create'].includes(event.kind));}
function clean(f){for(const line of f.lines)for(const marker of [q.marker,q.outRoot,...q.files,...logical])assert(!line.includes(marker));}
async function readReport(f,name='verification-report.json'){return JSON.parse(await fs.readFile(path.join(f.created,name),'utf8'));}
(async()=>{
  if(q.mode==='order'){
    const f=await fixture();assert.equal(await f.workflow.main(f.options),2);
    const lastChoice=f.events.findLastIndex(event=>event.kind==='choice');
    assert(f.events.findIndex(event=>event.kind==='inspect')>lastChoice);
    assert.equal(f.requests.length,8);assert.equal(f.restoreCalls,0);
    const report=await readReport(f);assert.equal(report.outcome,'review_required');
    assert.deepEqual(report.issues,['local-restore-not-ready']);assert.equal(report.restore_execution_verified,false);
    assert.equal(report.release_authorized,false);assert.equal(report.source_files.length,7);
    for(let index=0;index<7;index++){
      const name=api.INPUT_SLOTS[index].slot+(index===0?'.bin':'.json');
      assert.equal(hash(await fs.readFile(path.join(f.created,name))),hash(f.originals[index]));
      assert.equal(report.source_files[index].sha256,hash(f.originals[index]));
      assert.equal(hash(await fs.readFile(q.files[index])),hash(f.originals[index]));
    }
    assert.deepEqual(f.lines.filter(line=>line.startsWith('Выбран файл ')),api.INPUT_SLOTS.map((slot,index)=>`Выбран файл ${index+1} из 7: ${slot.label}.`));clean(f);
  }else if(q.mode==='cancel'||q.mode==='deny'||q.mode==='native-failure'||q.mode==='malformed'){
    const extra=q.mode==='cancel'?{cancelAt:q.at}:q.mode==='deny'?{deny:true}:
      q.mode==='malformed'?q.stderr?{rawErrorAt:q.at}:{malformedAt:q.at}:{failureAt:q.at,timeout:q.timeout};
    const f=await fixture(extra);assert.equal(await f.workflow.main(f.options),1);
    assert.equal(privateEvents(f).length,0);assert.equal(f.created,undefined);
    const expected=q.mode==='cancel'?'owner-selection-cancelled':q.mode==='deny'?'owner-scope-not-attested':
      q.mode==='malformed'&&!q.stderr?'owner-selection-invalid':q.timeout?'owner-selection-timeout':'owner-selection-failed';
    assert(f.lines.includes('Коды: '+expected));clean(f);
  }else if(q.mode==='duplicate-retry'||q.mode==='duplicate-correct'||q.mode==='duplicate-finish'){
    const choose=(index,file=index,lowercase=false)=>({mode:'choose',index,file,lowercase});
    const fix=q.mode==='duplicate-correct',finish=q.mode==='duplicate-finish';
    const duplicate={mode:'duplicate',index:fix?6:2,previous:1,
      response:fix?'correct-previous':finish?'selection-cancelled':'choose-current'};
    const plan=fix?[choose(0),choose(1,6),...Array.from({length:5},(_,index)=>choose(index+2)),duplicate,choose(1),choose(6)]:
      [choose(0),choose(1),choose(2,1,true),duplicate,...(finish?[]:Array.from({length:5},(_,index)=>choose(index+2)))];
    const f=await fixture({plan});assert.equal(await f.workflow.main(f.options),finish?1:2);assert.equal(f.remaining,0);
    if(finish){assert.equal(privateEvents(f).length,0);assert(f.lines.includes('Коды: owner-selection-cancelled'));}
    else{
      assert.deepEqual(f.requests.filter(item=>item.mode==='choose').map(item=>item.index),fix?[0,1,2,3,4,5,6,1,6]:[0,1,2,2,3,4,5,6]);
      assert(f.events.findIndex(event=>event.kind==='inspect')>f.events.findLastIndex(event=>event.kind==='choice'));
      const report=await readReport(f);for(let index=0;index<7;index++)assert.equal(report.source_files[index].sha256,hash(f.originals[index]));
    }clean(f);
  }else if(q.mode==='duplicate-inode'||q.mode==='total-limit'||q.mode==='io-error'||q.mode==='changed'||q.mode==='short-read'){
    const extra=q.mode==='duplicate-inode'?{duplicateInode:true}:q.mode==='total-limit'?{sizeOverride:20*1024*1024}:
      q.mode==='io-error'?{ioError:q.code}:q.mode==='changed'?{changed:true}:{shortRead:true};
    const f=await fixture(extra);assert.equal(await f.workflow.main(f.options),1);assert.equal(f.created,undefined);
    if(q.mode==='duplicate-inode'||q.mode==='total-limit'||q.mode==='io-error')assert.equal(f.events.filter(event=>event.kind==='read').length,0);
    const expected=q.mode==='duplicate-inode'?'duplicate-selected-file':q.mode==='total-limit'?'input-total-size-limit':
      q.mode==='io-error'?q.code:'input-file-changed';assert(f.lines.includes('Коды: '+expected));clean(f);
  }else if(q.mode==='restore'){
    const f=await fixture({restore:q.restore});const status=await f.workflow.main(f.options);
    assert.equal(status,q.restore==='passed'?0:1);
    const report=await readReport(f,q.restore==='passed'?'verification-report.json':'verification-failure.json');
    assert.equal(report.release_authorized,false);assert.equal(report.restore_execution_verified,q.restore==='passed');
    if(q.restore==='passed'){assert.equal(f.restoreCalls,1);assert.equal(report.outcome,'passed');}
    else assert(report.issues.includes(q.restore==='failed'?'local-restore-failed':'local-restore-unverified'));
    clean(f);
  }else if(q.mode==='comparison-review'){
    const changed=JSON.parse(await fs.readFile(q.files[5],'utf8'));changed.unknownFutureField={keep:q.marker};
    await fs.writeFile(q.files[5],JSON.stringify(changed));const f=await fixture({restore:'passed'});
    assert.equal(await f.workflow.main(f.options),2);const report=await readReport(f);
    assert.equal(report.restore_execution_verified,true);assert.equal(report.release_authorized,false);
    assert(report.issues.includes('device-export-diverges'));assert.equal(report.outcome,'review_required');clean(f);
  }else if(q.mode==='runtime'){
    for(const settings of [{platform:'linux',arch:'x64'},{platform:'win32',arch:'arm64'}]){
      const lines=[],workflow=api._createWorkflowForTests({...settings,log:line=>lines.push(line),
        load(){throw Error('must-not-load');},io:new Proxy({},{get(){throw Error('must-not-call-native');}}),
        execFile(){throw Error('must-not-select');}});
      assert.equal(await workflow.main({addonRoot:path.dirname(process.argv[1]),bundleRoot:path.dirname(path.dirname(process.argv[1]))}),1);
      assert.deepEqual(lines,['Результат: failed','Коды: unsupported-owner-runtime']);
    }
  }else if(q.mode==='paths'){
    for(const value of ['relative.json','\\\\host\\share.json','C:relative.json','C:\\a\\..\\b.json','C:\\a\\.\\b.json',
      'C:\\a\\\\b.json','C:\\a\\b.json\n','C:\\a\\b\u0000.json','C:\\a\\','C:\\','C:\\a\\file:stream',
      'C:\\a\\name.','C:\\a\\name ','C:\\a\\NUL.json','C:\\a\\COM1','C:/a/file.json'])
      assert.throws(()=>api._normalizedFileForTests(value,path),error=>error.code==='input-path-unsafe');
    const literal='C:\\Owner\\$(not-executed); `literal` \'quote\'.json';
    assert.equal(api._normalizedFileForTests(literal,path),literal);
  }else throw Error('unknown-case');
  process.stdout.write(JSON.stringify({outcome:'passed',case:q.mode,native_windows_tested:false}));
})().catch(()=>{process.stderr.write('fictional-windows-workflow-test-failed\n');process.exitCode=1;});
"""

ACTUAL_RESTORE_RUNNER = r"""
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs/promises');
const syncFs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const Module=require('node:module'),originalLoad=Module._load;
const q=JSON.parse(syncFs.readFileSync(0,'utf8')),addonRoot=path.dirname(process.argv[1]);
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const seen={engines:0,closed:false,artifacts:0};
global.fetch=()=>{throw Error('fictional-network-forbidden');};
Module._load=function(name,parent,isMain){
  const actual=Reflect.apply(originalLoad,this,[name,parent,isMain]);
  if(name==='./pglite/index.cjs')return {PGlite:{create:async(...args)=>{
    seen.engines++;const db=await actual.PGlite.create(...args),close=db.close.bind(db);
    db.close=async()=>{await close();assert.equal(db.closed,true);seen.closed=true;};return db;
  }}};
  return actual;
};
const api=require(process.argv[1]),restore=require(path.join(addonRoot,'local-restore.cjs')).restore;
const logical=q.files.map((_,index)=>'C:\\Fictional\\'+q.marker+'-'+index+'.json');
const events=[],lines=[];let created,choice=0;
function stable(st){return [st.dev,st.ino,st.size,st.mtimeNs,st.ctimeNs].map(x=>String(x)).join(':');}
function indexOf(filename){const index=logical.indexOf(filename);assert(index>=0);return index;}
const io={
  assertPlatform(){},getSystemDirectory(){return 'C:\\Windows\\System32';},
  async inspectInput(filename){const index=indexOf(filename);events.push('inspect');
    const st=await fs.stat(q.files[index],{bigint:true});
    return {filename,index,stat:{size:st.size},identity:stable(st),inode:String(st.dev)+':'+String(st.ino)};},
  async unchangedInput(proof){assert.equal(stable(await fs.stat(q.files[proof.index],{bigint:true})),proof.identity);},
  async readInput(proof){events.push('read');await io.unchangedInput(proof);
    const bytes=await fs.readFile(q.files[proof.index]);await io.unchangedInput(proof);return bytes;},
  async createPrivateDirectory(parent,prefix){assert.equal(parent,path.dirname(addonRoot));
    created=await fs.mkdtemp(path.join(q.outRoot,prefix));await fs.chmod(created,0o700);return created;},
  verifyPrivateDirectory(value){assert.equal(value,created);return true;},
  async writePrivate(directory,name,bytes){assert.equal(directory,created);
    await fs.writeFile(path.join(directory,name),bytes,{flag:'wx',mode:0o600});
    assert.equal(hash(await fs.readFile(path.join(directory,name))),hash(bytes));},
};
const workflow=api._createWorkflowForTests({platform:'win32',arch:'x64',io,log:line=>lines.push(line),
  execFile:async(executable,args,options)=>{
    events.push('choose');const request=JSON.parse(options.env.MARICHEVY_VERIFY_REQUEST);let result;
    if(choice++===0){assert.deepEqual(request,{mode:'attest'});result={result:'scope-confirmed'};}
    else{assert.deepEqual(request,{mode:'choose',index:choice-2});
      result={result:'file',path:Buffer.from(logical[choice-2],'utf8').toString('base64')};}
    return {stdout:JSON.stringify(result),stderr:''};
  }});
(async()=>{
  const originals=await Promise.all(q.files.map(async filename=>({bytes:await fs.readFile(filename),
    identity:stable(await fs.stat(filename,{bigint:true}))})));
  const status=await workflow.main({addonRoot,bundleRoot:path.dirname(addonRoot),restore:async options=>
    restore({...options,writePrivateArtifact:async(name,bytes)=>{
      assert.equal(seen.closed,true);seen.artifacts++;await options.writePrivateArtifact(name,bytes);
    }})});
  const matching=q.mode==='matching';assert.equal(status,matching?0:2);assert.equal(choice,8);
  assert(events.indexOf('inspect')>events.lastIndexOf('choose'));
  assert.equal(seen.engines,1);assert.equal(seen.closed,true);assert.equal(seen.artifacts,2);
  const report=JSON.parse(await fs.readFile(path.join(created,'verification-report.json'),'utf8'));
  assert.equal(report.outcome,matching?'passed':'review_required');assert.equal(report.restore_execution_verified,true);
  assert.equal(report.release_authorized,false);assert.equal(report.source_files.length,7);
  assert.deepEqual(report.issues,matching?[]:q.mode==='pending'?['pending-acknowledgement-required']:['conflict-packets']);
  const receipt=JSON.parse(await fs.readFile(path.join(created,'server-restore-receipt-PRIVATE.json'),'utf8'));
  assert.equal(receipt.restore_execution_verified,true);assert.equal(receipt.network_used,false);
  assert.equal(receipt.production_changed,false);assert.equal(receipt.original_files_modified,false);
  for(let index=0;index<7;index++){
    assert.equal(hash(await fs.readFile(q.files[index])),hash(originals[index].bytes));
    assert.equal(stable(await fs.stat(q.files[index],{bigint:true})),originals[index].identity);
    const name=api.INPUT_SLOTS[index].slot+(index===0?'.bin':'.json');
    assert.equal(hash(await fs.readFile(path.join(created,name))),hash(originals[index].bytes));
    assert.equal(report.source_files[index].sha256,hash(originals[index].bytes));
  }
  for(const line of lines)for(const privateValue of [q.marker,q.outRoot,...q.files,...logical])assert(!line.includes(privateValue));
  process.stdout.write(JSON.stringify({outcome:'passed',case:q.mode,native_windows_tested:false,actual_postgres_restore:true}));
})().catch(()=>{process.stderr.write('fictional-windows-integration-failed\n');process.exitCode=1;});
"""


class WindowsPrivateVerificationWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('Node required')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.fictional-windows-verifier-', dir=ROOT)
        self.root = Path(self.tmp.name)
        self.output = self.root / 'output'
        self.output.mkdir(mode=0o700)
        state = FIX.state()
        raw = FIX.dump(state)
        server = FIX.snapshot(raw)
        server['project_ref'] = 'kqndxecziamypdjpxhyq'
        capture = FIX.captured({'marichevy_state_v10': raw})
        self.files = []
        for index, value in enumerate([server, state, capture, state, capture, state, capture]):
            filename = self.root / f'{MARKER}-{index}.json'
            filename.write_text(FIX.dump(value), encoding='utf8')
            self.files.append(str(filename))

    def tearDown(self):
        self.tmp.cleanup()

    def run_case(self, mode, **extra):
        env = os.environ.copy()
        env.pop('NODE_OPTIONS', None)
        env.pop('NODE_PATH', None)
        request = {'mode': mode, 'files': self.files, 'outRoot': str(self.output), 'marker': MARKER, **extra}
        result = subprocess.run([self.node, '--no-global-search-paths', '-e', RUNNER, str(ENTRY)],
                                input=json.dumps(request), text=True, capture_output=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertNotIn(MARKER, result.stdout)
        self.assertEqual(json.loads(result.stdout), {'outcome': 'passed', 'case': mode, 'native_windows_tested': False})

    def test_unconfigured_import_cannot_touch_native_files_or_modules(self):
        script = r"""
const assert=require('node:assert/strict'),Module=require('node:module'),original=Module._load;
Module._load=function(name,parent,isMain){if(name.startsWith('node:')||name==='fs'||name==='child_process'||name==='koffi')throw Error('unexpected-access');return original.call(this,name,parent,isMain);};
const api=require(process.argv[1]),lines=[];console.log=line=>lines.push(line);
(async()=>{assert.equal(await api.main(),1);assert.deepEqual(lines,['Результат: failed','Коды: verified-launch-required']);assert.equal(api.INPUT_SLOTS.length,7);assert(Object.isFrozen(api.INPUT_SLOTS));process.stdout.write('{"outcome":"inert"}');})().catch(()=>{process.exitCode=1;});
"""
        result = subprocess.run([self.node, '-e', script, str(ENTRY)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'outcome': 'inert'})

    def test_all_seven_dialogs_precede_source_reads_and_copies(self):
        self.run_case('order')

    def test_cancel_at_scope_or_later_dialog_never_reads_sources(self):
        for at in (0, 1, 4, 7):
            with self.subTest(at=at):
                self.run_case('cancel', at=at)

    def test_scope_attestation_is_required(self):
        self.run_case('deny')

    def test_dialog_errors_timeouts_and_bad_transport_are_distinct_and_private(self):
        for at in (0, 1, 4):
            for timeout in (False, True):
                with self.subTest(at=at, timeout=timeout):
                    self.run_case('native-failure', at=at, timeout=timeout)
        self.run_case('malformed', at=2, stderr=False)
        self.run_case('malformed', at=2, stderr=True)

    def test_duplicate_retry_is_case_insensitive_and_preserves_choices(self):
        self.run_case('duplicate-retry')

    def test_duplicate_can_correct_previous_choice_then_resume_missing_slot(self):
        self.run_case('duplicate-correct')

    def test_finish_duplicate_dialog_never_reads_sources(self):
        self.run_case('duplicate-finish')

    def test_same_native_file_id_with_different_names_fails_before_body_read(self):
        self.run_case('duplicate-inode')

    def test_total_file_size_limit_fails_before_body_read(self):
        self.run_case('total-limit')

    def test_fixed_native_io_codes_propagate_without_exception_text(self):
        for code in ('input-path-unsafe', 'input-file-invalid', 'input-file-read-failed'):
            with self.subTest(code=code):
                self.run_case('io-error', code=code)

    def test_source_changed_or_short_read_never_reaches_output(self):
        self.run_case('changed')
        self.run_case('short-read')

    def test_mock_restore_contract_is_separate_and_never_authorizes_release(self):
        for restore in ('passed', 'failed', 'unverified'):
            with self.subTest(restore=restore):
                self.run_case('restore', restore=restore)

    def test_unknown_device_field_difference_remains_review_after_mock_restore(self):
        self.run_case('comparison-review')

    def test_unsupported_platform_or_arch_fails_before_imports_and_native_calls(self):
        self.run_case('runtime')

    def test_windows_paths_reject_ambiguous_names_without_shell_interpolation(self):
        self.run_case('paths')

    def actual_restore_case(self, mode):
        # Reuse only the existing deliberately fictional seven-file fixture.
        # Native WinAPI is substituted; the same strict core and actual WASM
        # PostgreSQL restoration run, including SQL/RLS/CAS and engine close.
        old, files, originals, wrapper_raw = INTEGRATION.PrivateVerificationIntegration().fixture(self.root, mode)
        request = {'mode': mode, 'files': [str(filename) for filename in files], 'outRoot': str(old), 'marker': INTEGRATION.MARKER}
        env = os.environ.copy()
        env.pop('NODE_OPTIONS', None)
        env.pop('NODE_PATH', None)
        result = subprocess.run([self.node, '--no-global-search-paths', '--max-old-space-size=512', '-e', ACTUAL_RESTORE_RUNNER, str(ENTRY)],
                                input=json.dumps(request), text=True, capture_output=True, env=env, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), {'outcome': 'passed', 'case': mode, 'native_windows_tested': False, 'actual_postgres_restore': True})
        for private in (INTEGRATION.MARKER, INTEGRATION.fixtures.MARKER, INTEGRATION.fixtures.HOUSE, str(self.root)):
            self.assertNotIn(private, result.stdout + result.stderr)
        folder, = old.iterdir()
        for filename, original in zip(files, originals):
            self.assertEqual(filename.read_bytes(), original)
        source = INTEGRATION.oracle.parse(wrapper_raw.encode())
        restored = INTEGRATION.oracle.parse((folder / 'server-restored-PRIVATE.json').read_bytes())
        source_tables, _, _ = INTEGRATION.oracle.snapshot(source, INTEGRATION.PROJECT, INTEGRATION.fixtures.HOUSE)
        restored_tables, restored_state, _ = INTEGRATION.oracle.snapshot(restored, INTEGRATION.PROJECT, INTEGRATION.fixtures.HOUSE)
        self.assertTrue(INTEGRATION.oracle_restore.compare_rows(source_tables, restored_tables))
        self.assertEqual(restored_state['futureExact'], Decimal(INTEGRATION.EXACT))
        self.assertEqual(restored_tables['family_chore_deliveries'][0]['telegram_message_id'], Decimal(9007199254740993))
        report = json.loads((folder / 'verification-report.json').read_bytes())
        self.assertTrue(report['restore_execution_verified'])
        self.assertFalse(report['release_authorized'])
        if mode == 'pending':
            self.assertEqual(report['counts']['pending_values'], 1)
        if mode == 'conflict':
            self.assertEqual(report['counts']['conflict_packets'], 1)

    def test_actual_seven_file_workflow_restores_same_tables_and_exact_numbers(self):
        self.actual_restore_case('matching')

    def test_actual_restore_does_not_override_pending_acknowledgement(self):
        self.actual_restore_case('pending')

    def test_actual_restore_does_not_override_preserved_conflict_packet(self):
        self.actual_restore_case('conflict')


if __name__ == '__main__':
    unittest.main()
