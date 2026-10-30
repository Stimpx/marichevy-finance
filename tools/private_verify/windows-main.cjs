'use strict';

// The Windows bootstrap checks the complete self-contained code closure before
// invoking this workflow. It reads only seven explicitly selected backup files.
const FIXED_PROJECT='kqndxecziamypdjpxhyq';
const MAX_FILE=32*1024*1024,MAX_TOTAL=128*1024*1024;
const INPUT_SLOTS=Object.freeze([
  Object.freeze({slot:'server',kind:'server',label:'серверная копия',prompt:'Файл 1 из 7. Серверная копия рабочей семьи: выбери CSV или JSON.'}),
  Object.freeze({slot:'mac-export',kind:'ordinary',label:'обычный JSON Mac',prompt:'Файл 2 из 7. Mac / Chrome, рабочая семья: выбери обычный JSON банка.'}),
  Object.freeze({slot:'mac-capture',kind:'capture',label:'очередь Mac',prompt:'Файл 3 из 7. Mac / Chrome, тот же профиль: выбери JSON частной очереди.'}),
  Object.freeze({slot:'iphone-export',kind:'ordinary',label:'обычный JSON iPhone',prompt:'Файл 4 из 7. iPhone / Safari, рабочая семья: выбери обычный JSON банка.'}),
  Object.freeze({slot:'iphone-capture',kind:'capture',label:'очередь iPhone',prompt:'Файл 5 из 7. iPhone / Safari, та же вкладка: выбери JSON частной очереди.'}),
  Object.freeze({slot:'windows-export',kind:'ordinary',label:'обычный JSON Windows',prompt:'Файл 6 из 7. Windows / рабочий браузер, рабочая семья: выбери обычный JSON банка.'}),
  Object.freeze({slot:'windows-capture',kind:'capture',label:'очередь Windows',prompt:'Файл 7 из 7. Windows / тот же профиль: выбери JSON частной очереди.'}),
]);
// No selected filename or other owner text is interpolated into this program.
// The request contains only a fixed mode and public slot indexes. Paths return
// as UTF-8/base64 in ASCII JSON, independent of the Windows console code page.
const UI_SCRIPT=String.raw`
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
try {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  [System.Windows.Forms.Application]::EnableVisualStyles()
  $request=$env:MARICHEVY_VERIFY_REQUEST | ConvertFrom-Json
  function Test-SlotIndex($value) {
    return (($value -is [int] -or $value -is [long]) -and $value -ge 0 -and $value -lt 7)
  }
  $slots=@(
    'Файл 1 из 7. Серверная копия рабочей семьи: выбери CSV или JSON.',
    'Файл 2 из 7. Mac / Chrome, рабочая семья: выбери обычный JSON банка.',
    'Файл 3 из 7. Mac / Chrome, тот же профиль: выбери JSON частной очереди.',
    'Файл 4 из 7. iPhone / Safari, рабочая семья: выбери обычный JSON банка.',
    'Файл 5 из 7. iPhone / Safari, та же вкладка: выбери JSON частной очереди.',
    'Файл 6 из 7. Windows / рабочий браузер, рабочая семья: выбери обычный JSON банка.',
    'Файл 7 из 7. Windows / тот же профиль: выбери JSON частной очереди.'
  )
  $response=@{result='selection-failed'}
  switch ($request.mode) {
    'attest' {
      $answer=[System.Windows.Forms.MessageBox]::Show('Выбирай только копии своего рабочего банка finance.marichev.pro: обычный JSON и отдельную очередь одного и того же профиля на каждом устройстве. Серверный файл должен быть выгружен из проверенного рабочего проекта Supabase. Исходные файлы останутся без изменений, частные результаты сохранятся на этом ноутбуке. Продолжить?','Частная сверка банка',[System.Windows.Forms.MessageBoxButtons]::YesNo,[System.Windows.Forms.MessageBoxIcon]::Information)
      if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {$response=@{result='scope-confirmed'}} else {$response=@{result='selection-cancelled'}}
    }
    'choose' {
      if (-not (Test-SlotIndex $request.index)) {throw 'invalid-request'}
      $picker=New-Object System.Windows.Forms.OpenFileDialog
      try {
        $picker.Title=$slots[$request.index]
        $picker.Filter='Копии банка (*.json;*.csv)|*.json;*.csv|Все файлы (*.*)|*.*'
        $picker.Multiselect=$false
        $picker.CheckFileExists=$true
        $picker.CheckPathExists=$true
        $picker.RestoreDirectory=$true
        if ($picker.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
          $response=@{result='file';path=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($picker.FileName))}
        } else {$response=@{result='selection-cancelled'}}
      } finally {$picker.Dispose()}
    }
    'duplicate' {
      if (-not (Test-SlotIndex $request.index) -or -not (Test-SlotIndex $request.previous) -or $request.index -eq $request.previous) {throw 'invalid-request'}
      $form=New-Object System.Windows.Forms.Form
      try {
        $form.Text='Файл уже выбран'
        $form.StartPosition='CenterScreen'
        $form.ClientSize=New-Object System.Drawing.Size(690,310)
        $form.FormBorderStyle='FixedDialog'
        $form.MaximizeBox=$false
        $form.MinimizeBox=$false
        $form.Font=New-Object System.Drawing.Font('Segoe UI',10)
        $label=New-Object System.Windows.Forms.Label
        $label.Location=New-Object System.Drawing.Point(18,18)
        $label.Size=New-Object System.Drawing.Size(654,225)
        $newline=[Environment]::NewLine
        $label.Text='Этот файл уже выбран для другого пункта:'+$newline+$slots[$request.previous]+$newline+$newline+'Сейчас запрашивается:'+$newline+$slots[$request.index]+$newline+$newline+'Предыдущие выборы сохранены. Выбери другой файл или исправь прежний выбор. Копирование или переименование того же файла не заменяет копию с нужного устройства.'
        $form.Controls.Add($label)
        $current=New-Object System.Windows.Forms.Button
        $current.Text='Выбрать другой'
        $current.Location=New-Object System.Drawing.Point(18,258)
        $current.Size=New-Object System.Drawing.Size(200,36)
        $current.DialogResult=[System.Windows.Forms.DialogResult]::Retry
        $form.Controls.Add($current)
        $previous=New-Object System.Windows.Forms.Button
        $previous.Text='Исправить прежний'
        $previous.Location=New-Object System.Drawing.Point(232,258)
        $previous.Size=New-Object System.Drawing.Size(220,36)
        $previous.DialogResult=[System.Windows.Forms.DialogResult]::Yes
        $form.Controls.Add($previous)
        $cancel=New-Object System.Windows.Forms.Button
        $cancel.Text='Завершить'
        $cancel.Location=New-Object System.Drawing.Point(466,258)
        $cancel.Size=New-Object System.Drawing.Size(200,36)
        $cancel.DialogResult=[System.Windows.Forms.DialogResult]::Cancel
        $form.Controls.Add($cancel)
        $form.AcceptButton=$current
        $form.CancelButton=$cancel
        $answer=$form.ShowDialog()
        if ($answer -eq [System.Windows.Forms.DialogResult]::Retry) {$response=@{result='choose-current'}} elseif ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {$response=@{result='correct-previous'}} else {$response=@{result='selection-cancelled'}}
      } finally {$form.Dispose()}
    }
    default {throw 'invalid-request'}
  }
  [Console]::Out.WriteLine(($response | ConvertTo-Json -Compress))
} catch {
  [Console]::Out.WriteLine('{"result":"selection-failed"}')
}
`;
const OWN_CODES=new Set(['verified-launch-required','unsupported-owner-runtime',
  'owner-selection-cancelled','owner-selection-failed','owner-selection-invalid','owner-selection-timeout',
  'owner-scope-not-attested','input-path-unsafe','input-file-invalid','input-file-size-limit',
  'input-total-size-limit','input-file-changed','input-file-read-failed','input-file-close-failed',
  'duplicate-selected-file','private-directory-failed','private-output-failed','private-output-changed',
  'local-core-not-ready','local-restore-not-ready','local-restore-failed','local-restore-unverified',
  'local-verification-failed']);
class WorkflowError extends Error {
  constructor(code){const safe=OWN_CODES.has(code)?code:'local-verification-failed';
    super(safe);this.name='WorkflowError';this.code=safe;}
}
const fail=code=>{throw new WorkflowError(code);};
function safeIssue(code){return typeof code==='string'&&/^[a-z][a-z0-9-]{0,80}$/.test(code)?code:'local-verification-failed';}
function normalizedFile(value,path){
  if(typeof value!=='string'||!/^([A-Za-z]):\\/.test(value)||value.length>32760||
    /[\x00-\x1f\x7f/:]/.test(value.slice(2))||value.endsWith('\\')||path.win32.normalize(value)!==value||
    value.slice(3).split('\\').some(part=>!part||part==='.'||part==='..'||/[ .]$/.test(part)||
      part.length>255||/^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(part)))fail('input-path-unsafe');
  return value;
}
function createWorkflow(injected={}){
  const path=injected.path??require('node:path');
  const crypto=injected.crypto??require('node:crypto');
  const platform=injected.platform??process.platform,arch=injected.arch??process.arch;
  const log=injected.log??(line=>console.log(line));
  const run=injected.execFile??require('node:util').promisify(require('node:child_process').execFile);
  const load=injected.load??(filename=>require(filename));
  let io=injected.io,running=false;
  const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
  function localIO(){if(!io)io=load(path.join(__dirname,'windows-io.cjs'));return io;}
  async function nativeRun(request){
    try{
      const systemDirectory=localIO().getSystemDirectory();
      normalizedFile(path.win32.join(systemDirectory,'WindowsPowerShell','v1.0','powershell.exe'),path);
      const systemRoot=path.win32.dirname(systemDirectory);
      const result=await run(path.win32.join(systemDirectory,'WindowsPowerShell','v1.0','powershell.exe'),
        ['-NoLogo','-NoProfile','-NonInteractive','-STA','-EncodedCommand',Buffer.from(UI_SCRIPT,'utf16le').toString('base64')],
        {encoding:'utf8',timeout:600000,maxBuffer:32*1024,windowsHide:true,
          env:{SystemRoot:systemRoot,WINDIR:systemRoot,MARICHEVY_VERIFY_REQUEST:JSON.stringify(request)}});
      if(typeof result?.stdout!=='string'||result.stderr?.trim())fail('owner-selection-failed');
      let value;try{value=JSON.parse(result.stdout.trim());}catch(_){fail('owner-selection-invalid');}
      if(!value||typeof value!=='object'||Array.isArray(value)||typeof value.result!=='string')fail('owner-selection-invalid');
      const fields=Object.keys(value).sort().join(',');
      if(value.result==='file'){
        if(fields!=='path,result'||typeof value.path!=='string'||value.path.length>48*1024||
          !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value.path))fail('owner-selection-invalid');
        const bytes=Buffer.from(value.path,'base64');
        if(bytes.toString('base64')!==value.path)fail('owner-selection-invalid');
        try{return normalizedFile(new TextDecoder('utf-8',{fatal:true}).decode(bytes),path);}
        catch(error){if(error instanceof WorkflowError)throw error;fail('owner-selection-invalid');}
      }
      if(fields!=='result')fail('owner-selection-invalid');
      if(!['scope-confirmed','selection-cancelled','selection-failed','choose-current','correct-previous'].includes(value.result))fail('owner-selection-invalid');
      if(value.result==='selection-failed')fail('owner-selection-failed');
      return value.result;
    }catch(error){
      if(error instanceof WorkflowError)throw error;
      // Raw PowerShell/OS messages can contain selected filenames. Never log them.
      fail(error?.killed===true?'owner-selection-timeout':'owner-selection-failed');
    }
  }
  async function selectInputs(){
    const attested=await nativeRun({mode:'attest'});
    if(attested==='selection-cancelled')fail('owner-selection-cancelled');
    if(attested!=='scope-confirmed')fail('owner-scope-not-attested');
    const selected=Array(INPUT_SLOTS.length).fill(null);let index=0;
    while(index!==-1){
      const slot=INPUT_SLOTS[index],chosen=await nativeRun({mode:'choose',index});
      if(chosen==='selection-cancelled')fail('owner-selection-cancelled');
      const filename=normalizedFile(chosen,path);
      const previous=selected.findIndex((item,position)=>position!==index&&item?.filename.toLowerCase()===filename.toLowerCase());
      if(previous!==-1){
        const action=await nativeRun({mode:'duplicate',index,previous});
        if(action==='selection-cancelled')fail('owner-selection-cancelled');
        if(action==='correct-previous'){index=previous;continue;}
        if(action==='choose-current')continue;
        fail('owner-selection-invalid');
      }
      selected[index]={slot,filename};
      log('Выбран файл '+(index+1)+' из '+INPUT_SLOTS.length+': '+slot.label+'.');
      index=selected.findIndex(item=>item===null);
    }
    return selected;
  }
  function output(outcome,issues){
    log('Результат: '+(['passed','review_required','failed'].includes(outcome)?outcome:'failed'));
    log('Коды: '+(issues.length?[...new Set(issues.map(safeIssue))].sort().join(', '):'none'));
  }
  async function main(options={}){
    if(running){output('failed',['verified-launch-required']);return 2;}
    running=true;let report,outputDir,outputVerified=false;
    try{
      if(options.addonRoot!==__dirname||options.bundleRoot!==path.dirname(__dirname))fail('verified-launch-required');
      if(platform!=='win32'||arch!=='x64')fail('unsupported-owner-runtime');
      const adapter=localIO();adapter.assertPlatform();
      const core=load(path.join(options.addonRoot,'core.cjs'));
      const decoder=load(path.join(options.addonRoot,'owner-export.cjs'));
      if(core.STATUS?.ready!==true||typeof decoder.decodeOwnerExport!=='function')fail('local-core-not-ready');
      log('Этап: выбор семи копий');
      const selected=await selectInputs(); // No selected-file I/O before all seven choices finish.
      log('Этап: проверка выбранных файлов');
      const proofs=[],inodes=new Set();let total=0;
      for(const item of selected){
        const proof=await adapter.inspectInput(item.filename,MAX_FILE);
        if(!proof||typeof proof.stat?.size!=='bigint'||proof.stat.size<=0n||proof.stat.size>BigInt(MAX_FILE))fail('input-file-size-limit');
        if(typeof proof.inode!=='string'||!proof.inode)fail('input-file-invalid');
        if(inodes.has(proof.inode))fail('duplicate-selected-file');inodes.add(proof.inode);
        total+=Number(proof.stat.size);if(total>MAX_TOTAL)fail('input-total-size-limit');
        proofs.push({...item,proof});
      }
      const inputs=[];
      for(const item of proofs){
        const bytes=await adapter.readInput(item.proof);
        if(!Buffer.isBuffer(bytes)||BigInt(bytes.length)!==item.proof.stat.size)fail('input-file-changed');
        inputs.push({...item,bytes});
      }
      for(const item of proofs)await adapter.unchangedInput(item.proof);
      const decoded=decoder.decodeOwnerExport(inputs[0].bytes);
      const server=core.parse(decoded.backupJson),household=server.configured_household;
      core.snapshot(server,FIXED_PROJECT,household);
      const devices=[];
      for(let index=1;index<inputs.length;index+=2)devices.push({exported:core.parse(inputs[index].bytes),
        captured:core.parse(inputs[index+1].bytes),scope_verified_by_owner:true});
      log('Этап: сравнение копий');
      const compared=core.compareDevices({server,devices,project:FIXED_PROJECT,household,scopeAttested:true});
      report={...compared,format:'marichevy-private-local-verification-v1',
        phase:'device-comparison-and-optional-local-restore',restore_execution_verified:false,release_authorized:false,
        source_files:inputs.map(item=>({slot:item.slot.slot,bytes:item.bytes.byteLength,sha256:digest(item.bytes)}))};
      if(!Array.isArray(report.issues)||!['passed','review_required','failed'].includes(report.outcome))fail('local-verification-failed');
      report.issues=report.issues.map(safeIssue);
      try{
        outputDir=await adapter.createPrivateDirectory(options.bundleRoot,'PRIVATE-verification-');
        await adapter.verifyPrivateDirectory(outputDir);
      }catch(_){fail('private-directory-failed');}
      outputVerified=true;
      for(const item of inputs)await adapter.writePrivate(outputDir,item.slot.slot+(item.slot.kind==='server'?'.bin':'.json'),item.bytes);
      if(report.outcome!=='failed'){
        if(typeof options.restore!=='function'){
          report.issues.push('local-restore-not-ready');report.outcome='review_required';
        }else{
          log('Этап: локальная проверка восстановления');let restored;
          try{restored=await options.restore({backupJson:decoded.backupJson,server,project:FIXED_PROJECT,household,
            writePrivateArtifact:(name,bytes)=>adapter.writePrivate(outputDir,name,bytes)});}
          catch(_){fail('local-restore-failed');}
          if(restored?.restore_execution_verified!==true||restored?.outcome!=='passed')fail('local-restore-unverified');
          report.restore_execution_verified=true;report.restore={outcome:'passed',restore_execution_verified:true};
        }
      }
      report.issues=[...new Set(report.issues)].sort();
      await adapter.writePrivate(outputDir,'verification-report.json',Buffer.from(JSON.stringify(report,null,2)+'\n','utf8'));
      output(report.outcome,report.issues);
      log('Частные копии и отчёт сохранены в новой папке PRIVATE-verification-… рядом с программой сверки.');
      log('В чат сообщи только результат и коды.');
      return report.outcome==='passed'?0:report.outcome==='review_required'?2:1;
    }catch(error){
      const code=error instanceof WorkflowError?error.code:
        error?.name==='WindowsIOError'&&OWN_CODES.has(error.code)?error.code:
        (error?.name==='InvalidBackup'||error?.name==='OwnerExportError')?safeIssue(error.code):'local-verification-failed';
      if(report&&outputVerified){
        const failed={...report,outcome:'failed',restore_execution_verified:false,release_authorized:false,
          issues:[...new Set([...report.issues,code])].sort()};
        try{await localIO().writePrivate(outputDir,'verification-failure.json',Buffer.from(JSON.stringify(failed,null,2)+'\n','utf8'));}catch(_){}
      }
      output('failed',[code]);return 1;
    }finally{running=false;}
  }
  return Object.freeze({main,selectInputs});
}
async function main(options){
  // An accidental direct import cannot open native dialogs, files, or modules.
  if(!options||options.addonRoot!==__dirname||typeof options.bundleRoot!=='string'){
    console.log('Результат: failed');console.log('Коды: verified-launch-required');return 1;
  }
  return createWorkflow().main(options);
}
module.exports=Object.freeze({main,FIXED_PROJECT,INPUT_SLOTS,MAX_FILE,MAX_TOTAL,WorkflowError,
  _createWorkflowForTests:createWorkflow,_normalizedFileForTests:normalizedFile,_uiScriptForTests:UI_SCRIPT});
