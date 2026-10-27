'use strict';

// The bootstrap validates both code closures before invoking this owner-local
// workflow. Originals remain read only; comparison never implies a restore.
const FIXED_PROJECT='kqndxecziamypdjpxhyq';
const MAX_FILE=32*1024*1024, MAX_TOTAL=128*1024*1024;
const INPUT_SLOTS=Object.freeze([
  Object.freeze({slot:'server',kind:'server',prompt:'Серверная копия рабочей семьи: выбери CSV или JSON.'}),
  Object.freeze({slot:'mac-export',kind:'ordinary',prompt:'Mac / Chrome, рабочая семья: выбери обычный JSON банка.'}),
  Object.freeze({slot:'mac-capture',kind:'capture',prompt:'Mac / Chrome, тот же профиль: выбери JSON частной очереди.'}),
  Object.freeze({slot:'iphone-export',kind:'ordinary',prompt:'iPhone / Safari, рабочая семья: выбери обычный JSON банка.'}),
  Object.freeze({slot:'iphone-capture',kind:'capture',prompt:'iPhone / Safari, та же вкладка: выбери JSON частной очереди.'}),
  Object.freeze({slot:'windows-export',kind:'ordinary',prompt:'Windows / рабочий браузер, рабочая семья: выбери обычный JSON банка.'}),
  Object.freeze({slot:'windows-capture',kind:'capture',prompt:'Windows / тот же профиль: выбери JSON частной очереди.'}),
]);
const ATTEST_SCRIPT='on run argv\n'+
  'display dialog "Выбирай только копии своего рабочего банка finance.marichev.pro: обычный JSON и отдельную очередь одного и того же профиля на каждом устройстве. Серверный файл должен быть выгружен из проверенного рабочего проекта Supabase. Файлы останутся на этом Mac. Продолжить?" '+
  'buttons {"Отмена", "Подтверждаю"} default button "Подтверждаю" cancel button "Отмена" with title "Частная сверка банка"\n'+
  'return "scope-confirmed"\nend run';
const CHOOSE_SCRIPT='on run argv\n'+
  'set selectedFile to choose file with prompt (item 1 of argv)\n'+
  'return POSIX path of selectedFile\nend run';
const OWN_CODES=new Set(['verified-launch-required','unsupported-owner-runtime',
  'owner-selection-cancelled','owner-selection-failed','owner-selection-invalid',
  'owner-scope-not-attested','input-path-unsafe','input-file-invalid',
  'input-file-size-limit','input-total-size-limit','input-file-changed',
  'input-file-read-failed','input-file-close-failed','duplicate-selected-file',
  'private-directory-failed','private-output-failed','private-output-changed',
  'local-core-not-ready','local-restore-not-ready','local-restore-failed',
  'local-restore-unverified','local-verification-failed']);
class WorkflowError extends Error {
  constructor(code){const safe=OWN_CODES.has(code)?code:'local-verification-failed';
    super(safe);this.name='WorkflowError';this.code=safe;}
}
const fail=code=>{throw new WorkflowError(code);};
function normalizedFile(value,path){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||
    Buffer.byteLength(value,'utf8')>4096||/[\x00-\x1f\x7f]/.test(value)||
    value.split('/').some(part=>part==='.'||part==='..'||Buffer.byteLength(part,'utf8')>255)||
    path.posix.normalize(value)!==value||value==='/'||value.endsWith('/')) fail('input-path-unsafe');
  return value;
}
function identity(stat,{content=false}={}){
  const fields=['dev','ino','uid','gid','mode','nlink'];
  if(content)fields.push('size','mtimeNs','ctimeNs');
  if(fields.some(key=>typeof stat[key]!=='bigint'))fail('input-file-invalid');
  return fields.map(key=>stat[key].toString()).join(':');
}
function safeIssue(code){
  // Only trusted verifier classes supply a code here. No raw exception message.
  return typeof code==='string'&&/^[a-z][a-z0-9-]{0,80}$/.test(code)?code:'local-verification-failed';
}
function createWorkflow(injected={}){
  const fs=injected.fs??require('node:fs/promises');
  const constants=injected.constants??require('node:fs').constants;
  const path=injected.path??require('node:path');
  const crypto=injected.crypto??require('node:crypto');
  const platform=injected.platform??process.platform;
  const arch=injected.arch??process.arch;
  const uid=injected.uid??(()=>process.getuid?.());
  const euid=injected.euid??(()=>process.geteuid?.());
  const log=injected.log??(line=>console.log(line));
  const run=injected.execFile??require('node:util').promisify(require('node:child_process').execFile);
  const load=injected.load??(filename=>require(filename));
  const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
  let running=false;
  function ownerUid(){
    const owner=uid();
    if(platform!=='darwin'||!['arm64','x64'].includes(arch)||!Number.isSafeInteger(owner)||owner<=0||euid()!==owner)
      fail('unsupported-owner-runtime');
    return BigInt(owner);
  }
  async function nativeRun(script,args=[]){
    try{
      const result=await run('/usr/bin/osascript',['-e',script,'--',...args],
        {encoding:'utf8',timeout:600000,maxBuffer:16*1024,windowsHide:true});
      if(typeof result?.stdout!=='string'||result.stderr?.trim())fail('owner-selection-failed');
      return result.stdout.replace(/\r?\n$/,'');
    }catch(error){
      if(error instanceof WorkflowError)throw error;
      // Do not parse stderr, which may contain a private path.
      fail('owner-selection-cancelled');
    }
  }
  async function selectInputs(){
    if(await nativeRun(ATTEST_SCRIPT)!=='scope-confirmed')fail('owner-scope-not-attested');
    const selected=[];
    for(const slot of INPUT_SLOTS){
      const filename=normalizedFile(await nativeRun(CHOOSE_SCRIPT,[slot.prompt]),path);
      if(selected.some(item=>item.filename===filename))fail('duplicate-selected-file');
      selected.push({slot,filename});
    }
    return selected;
  }
  async function inspectInput(filename,owner){
    normalizedFile(filename,path);
    const parents=[];let current='/';
    for(const component of [''].concat(path.posix.dirname(filename).split('/').filter(Boolean))){
      if(component)current=path.posix.join(current,component);
      const stat=await fs.lstat(current,{bigint:true});
      if(!stat.isDirectory()||stat.isSymbolicLink()||![0n,owner].includes(stat.uid)||
        (stat.mode&0o022n)!==0n)fail('input-path-unsafe');
      parents.push({filename:current,identity:identity(stat)});
    }
    if(await fs.realpath(filename)!==filename)fail('input-path-unsafe');
    const stat=await fs.lstat(filename,{bigint:true});
    if(!stat.isFile()||stat.isSymbolicLink()||stat.uid!==owner||stat.nlink!==1n)fail('input-file-invalid');
    if(stat.size<=0n||stat.size>BigInt(MAX_FILE))fail('input-file-size-limit');
    return {filename,owner,parents,stat,identity:identity(stat,{content:true}),inode:stat.dev+':'+stat.ino};
  }
  async function unchangedInput(proof){
    if(await fs.realpath(proof.filename)!==proof.filename)fail('input-file-changed');
    for(const parent of proof.parents){
      const stat=await fs.lstat(parent.filename,{bigint:true});
      if(!stat.isDirectory()||stat.isSymbolicLink()||identity(stat)!==parent.identity)fail('input-file-changed');
    }
    const stat=await fs.lstat(proof.filename,{bigint:true});
    if(!stat.isFile()||stat.isSymbolicLink()||identity(stat,{content:true})!==proof.identity)
      fail('input-file-changed');
  }
  async function readInput(proof){
    let handle,failed=false;
    try{
      await unchangedInput(proof);
      if(!Number.isInteger(constants.O_NOFOLLOW)||!Number.isInteger(constants.O_NONBLOCK))fail('input-path-unsafe');
      handle=await fs.open(proof.filename,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
      const opened=await handle.stat({bigint:true});
      if(!opened.isFile()||identity(opened,{content:true})!==proof.identity)fail('input-file-changed');
      const data=Buffer.alloc(Number(opened.size));let position=0;
      while(position<data.length){
        const result=await handle.read({buffer:data,offset:position,length:Math.min(data.length-position,1024*1024),position});
        if(!Number.isSafeInteger(result.bytesRead)||result.bytesRead<=0)fail('input-file-changed');
        position+=result.bytesRead;
      }
      const extra=await handle.read({buffer:Buffer.alloc(1),offset:0,length:1,position});
      if(extra.bytesRead!==0||identity(await handle.stat({bigint:true}),{content:true})!==proof.identity)
        fail('input-file-changed');
      await unchangedInput(proof);return data;
    }catch(error){failed=true;throw error instanceof WorkflowError?error:new WorkflowError('input-file-read-failed');}
    finally{if(handle)try{await handle.close();}catch(_){if(!failed)fail('input-file-close-failed');}}
  }
  async function writePrivate(directory,name,bytes,owner){
    if(typeof name!=='string'||!/^[a-z][a-zA-Z0-9-]{0,63}\.(?:json|bin)$/.test(name)||!(bytes instanceof Uint8Array)||
      bytes.byteLength===0||bytes.byteLength>MAX_FILE)
      fail('private-output-failed');
    const filename=path.posix.join(directory,name);let handle,proof,writtenIdentity;
    try{
      handle=await fs.open(filename,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600);
      proof=await handle.stat({bigint:true});
      if(!proof.isFile()||proof.uid!==owner||proof.nlink!==1n||(proof.mode&0o777n)!==0o600n)
        fail('private-output-failed');
      await handle.writeFile(bytes);await handle.sync();
      const after=await handle.stat({bigint:true});
      if(after.dev!==proof.dev||after.ino!==proof.ino||after.uid!==owner||after.nlink!==1n||
        (after.mode&0o777n)!==0o600n||after.size!==BigInt(bytes.byteLength))fail('private-output-changed');
      writtenIdentity=identity(after,{content:true});
    }catch(error){throw error instanceof WorkflowError?error:new WorkflowError('private-output-failed');}
    finally{if(handle)try{await handle.close();}catch(_){fail('private-output-failed');}}
    const readProof=await inspectInput(filename,owner);
    if(readProof.identity!==writtenIdentity||(readProof.stat.mode&0o777n)!==0o600n)
      fail('private-output-changed');
    const copied=await readInput(readProof);
    if(digest(copied)!==digest(bytes))fail('private-output-changed');
  }
  function output(outcome,issues){
    log('Результат: '+(['passed','review_required','failed'].includes(outcome)?outcome:'failed'));
    log('Коды: '+(issues.length?[...new Set(issues.map(safeIssue))].sort().join(', '):'none'));
  }
  async function main(options={}){
    if(running){output('failed',['verified-launch-required']);return 2;}
    running=true;
    let report,outputDir,owner,outputVerified=false;
    try{
      // Only these two bootstrap-validated closures can supply imports.
      if(typeof options.oldBundleRoot!=='string'||options.addonRoot!==__dirname||
        !path.posix.isAbsolute(options.oldBundleRoot)||options.oldBundleRoot===options.addonRoot)
        fail('verified-launch-required');
      owner=ownerUid();
      const core=load(path.posix.join(options.addonRoot,'core.cjs'));
      const decoder=load(path.posix.join(options.addonRoot,'owner-export.cjs'));
      log('Этап: загрузка системного модуля');
      const macos=load(path.posix.join(options.oldBundleRoot,'app','macos.cjs'));
      if(core.STATUS?.ready!==true||typeof decoder.decodeOwnerExport!=='function'||typeof macos.createPrivateDirectory!=='function')
        fail('local-core-not-ready');
      log('Этап: выбор семи копий');
      const selected=await selectInputs(); // Every chooser finishes before input I/O.
      log('Этап: проверка выбранных файлов');
      const proofs=[],inodes=new Set();let total=0;
      for(const item of selected){
        const proof=await inspectInput(item.filename,owner);
        if(inodes.has(proof.inode))fail('duplicate-selected-file');inodes.add(proof.inode);
        total+=Number(proof.stat.size);if(total>MAX_TOTAL)fail('input-total-size-limit');
        proofs.push({...item,proof});
      }
      const inputs=[];
      for(const item of proofs)inputs.push({...item,bytes:await readInput(item.proof)});
      for(const item of proofs)await unchangedInput(item.proof);
      const decoded=decoder.decodeOwnerExport(inputs[0].bytes);
      const server=core.parse(decoded.backupJson),household=server.configured_household;
      core.snapshot(server,FIXED_PROJECT,household);
      const devices=[];
      for(let index=1;index<inputs.length;index+=2)devices.push({
        exported:core.parse(inputs[index].bytes),captured:core.parse(inputs[index+1].bytes),scope_verified_by_owner:true});
      log('Этап: сравнение копий');
      const compared=core.compareDevices({server,devices,project:FIXED_PROJECT,household,scopeAttested:true});
      report={...compared,format:'marichevy-private-local-verification-v1',
        phase:'device-comparison-and-optional-local-restore',restore_execution_verified:false,release_authorized:false,
        source_files:inputs.map(item=>({slot:item.slot.slot,bytes:item.bytes.byteLength,sha256:digest(item.bytes)}))};
      if(!Array.isArray(report.issues)||!['passed','review_required','failed'].includes(report.outcome))
        fail('local-verification-failed');
      report.issues=report.issues.map(safeIssue);
      try{outputDir=await macos.createPrivateDirectory(options.oldBundleRoot,'PRIVATE-verification-');}
      catch(_){fail('private-directory-failed');}
      const outputStat=await fs.lstat(outputDir,{bigint:true});
      if(!outputStat.isDirectory()||outputStat.isSymbolicLink()||outputStat.uid!==owner||
        (outputStat.mode&0o777n)!==0o700n)fail('private-directory-failed');
      outputVerified=true;
      for(const item of inputs)await writePrivate(outputDir,item.slot.slot+(item.slot.kind==='server'?'.bin':'.json'),item.bytes,owner);
      if(report.outcome!=='failed'){
        if(typeof options.restore!=='function'){
          report.issues.push('local-restore-not-ready');report.outcome='review_required';
        }else{
          let restored;
          log('Этап: локальная проверка восстановления');
          try{restored=await options.restore({backupJson:decoded.backupJson,server,project:FIXED_PROJECT,household,
            writePrivateArtifact:(name,bytes)=>writePrivate(outputDir,name,bytes,owner)});}
          catch(_){fail('local-restore-failed');}
          if(restored?.restore_execution_verified!==true||restored?.outcome!=='passed')fail('local-restore-unverified');
          report.restore_execution_verified=true;
          report.restore={outcome:'passed',restore_execution_verified:true};
        }
      }
      report.issues=[...new Set(report.issues)].sort();
      await writePrivate(outputDir,'verification-report.json',Buffer.from(JSON.stringify(report,null,2)+'\n','utf8'),owner);
      output(report.outcome,report.issues);
      log('Частные копии и отчёт сохранены в новой папке PRIVATE-verification-… рядом с помощником.');
      log('В чат сообщи только результат и коды.');
      return report.outcome==='passed'?0:report.outcome==='review_required'?2:1;
    }catch(error){
      const code=error instanceof WorkflowError?error.code:
        (error?.name==='InvalidBackup'||error?.name==='OwnerExportError')?safeIssue(error.code):'local-verification-failed';
      if(report&&outputVerified&&owner!==undefined){
        const failed={...report,outcome:'failed',restore_execution_verified:false,release_authorized:false,
          issues:[...new Set([...report.issues,code])].sort()};
        try{await writePrivate(outputDir,'verification-failure.json',Buffer.from(JSON.stringify(failed,null,2)+'\n','utf8'),owner);}
        catch(_){} // Original failure remains fixed; never disclose filesystem text.
      }
      output('failed',[code]);return 1;
    }finally{running=false;}
  }
  return Object.freeze({main,selectInputs,inspectInput,unchangedInput,readInput,writePrivate});
}
async function main(options){
  // Keep the unconfigured entry inert even during require() instrumentation.
  if(!options||typeof options.oldBundleRoot!=='string'||!options.oldBundleRoot.startsWith('/')||
    options.addonRoot!==__dirname||options.oldBundleRoot===options.addonRoot){
    console.log('Результат: failed');console.log('Коды: verified-launch-required');return 1;
  }
  return createWorkflow().main(options);
}
module.exports=Object.freeze({main,FIXED_PROJECT,INPUT_SLOTS,MAX_FILE,MAX_TOTAL,WorkflowError,
  implementation_status:'device-workflow-ready-restore-hook-required',_createWorkflowForTests:createWorkflow,
  _identityForTests:identity,_normalizedFileForTests:normalizedFile,
  _scriptsForTests:Object.freeze({attest:ATTEST_SCRIPT,choose:CHOOSE_SCRIPT})});

