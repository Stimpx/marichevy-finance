'use strict';

// Local offline application. No browser code, browser launch or network calls.
const fs=require('node:fs/promises');
const path=require('node:path');
const readline=require('node:readline/promises');
const {fork}=require('node:child_process');
const {ClassicLevel}=require('classic-level');
const macos=require('./macos.cjs');
const core=require('./capture.cjs');
const {validateClone}=require('./integrity.cjs');
const MESSAGES=Object.freeze({
  MAC_UNSUPPORTED:'Нужен Mac с процессором Apple Silicon или Intel и обычная учётная запись без sudo.',
  MAC_BINDINGS_UNAVAILABLE:'Системный модуль недоступен. Используйте весь проверенный комплект.',
  BROWSER_RUNNING:'Chrome или Яндекс ещё работает. Полностью закройте браузеры через меню «Завершить».',
  BROWSER_CHECK_FAILED:'Не удалось проверить закрытие браузеров. Копия не создана.',
  SOURCE_PATH_UNSAFE:'Нужна обычная локальная папка профиля без ссылок и общего доступа.',
  SOURCE_INVALID:'Не удалось безопасно прочитать папку профиля.',
  SOURCE_LOCK_UNAVAILABLE:'Хранилище ещё занято или его LOCK недоступен. Копия не создана.',
  SOURCE_LOCK_RELEASE_FAILED:'Не удалось закрыть защитный дескриптор. Завершите помощник.',
  PRIVATE_ACL_UNAVAILABLE:'Не удалось подтвердить закрытый доступ к новой папке. Копирование остановлено.',
  PRIVATE_DIRECTORY_FAILED:'Не удалось создать закрытую папку. Исходные файлы не менялись.',
  'invalid-profile-path':'Вставьте только путь из chrome://version, строка «Путь к профилю».',
  'selftest-failed':'Встроенная проверка не пройдена. Ваш профиль не читался.',
  'unsupported-sqlite-storage':'Формат хранения этого браузера пока не поддерживается.',
  'no-financial-keys':'В этом профиле не найдены записи банка. Другой профиль этим не проверен.',
  'source-changed':'При чтении источник изменился. Копия не создана.',
  'source-size-limit':'Хранилище превышает проверенный размер. Исходник не менялся.',
  'capture-size-limit':'Копия превышает проверенный размер. Файл не сохранён.',
  'integrity-validation-failed':'Целостность хранилища не подтверждена. Не очищайте и не исправляйте его.',
  'clone-cleanup-failed':'Не удалось удалить временную частную копию. Основной резерв не создан.',
  'capture-failed':'Копирование остановлено. Сообщите только код ошибки; исходники оставьте на месте.'
});
function profilePath(text){
  let value=String(text??'').trim();
  if(value.startsWith('"')&&value.endsWith('"'))value=value.slice(1,-1);
  try{return macos._localPathForTests(value);}catch(_){throw Object.assign(new Error(),{code:'invalid-profile-path'});}
}
async function openDatabase(directory,options,proof){
  if(!proof||proof.validated!==true||proof.checksumSource!=='external-crc32c-preflight')
    throw new core.CaptureError('engine-checksums-unverified');
  return new ClassicLevel(directory,options);
}
function contender(filename){
  const env={...process.env};delete env.NODE_OPTIONS;delete env.NODE_PATH;
  const child=fork(path.join(__dirname,'macos.cjs'),['--selftest-contender'],
    {silent:true,execArgv:[],env});
  const completed=new Promise((resolve,reject)=>{
    child.once('error',reject);child.once('exit',(code,signal)=>code===0&&!signal?resolve():reject(new Error()));
  });
  completed.catch(()=>{});
  const result=new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{child.kill();reject(new Error());},10000);
    child.once('message',message=>{clearTimeout(timeout);resolve(message?.outcome);});
    child.once('error',()=>{clearTimeout(timeout);reject(new Error());});
    child.once('exit',()=>{clearTimeout(timeout);reject(new Error());});
  });
  child.stdout.resume();child.stderr.resume();
  child.send({type:'try-writer',filename});
  return {child,result,completed};
}
async function selftest(outputDir){
  console.log('Самопроверка: private-directory');
  const root=await macos.createPrivateDirectory(outputDir,'selftest-');let database,writer;
  try{
    console.log('Самопроверка: fictional-fixture');
    const source=path.join(root,'fictional-profile','Local Storage','leveldb');
    await fs.mkdir(source,{recursive:true,mode:0o700});
    database=new ClassicLevel(source,{keyEncoding:'buffer',valueEncoding:'buffer'});await database.open();
    const key=(name,origin=core.ORIGIN)=>Buffer.concat([Buffer.from('_'+origin+'\0'),Buffer.from([1]),Buffer.from(name,'latin1')]);
    const encoded=value=>Buffer.concat([Buffer.from([0]),Buffer.from(value,'utf16le')]);
    const raw='{"entries":[],"note":"Только учебная проверка","exact":9007199254740993,"lone":"\ud800"}';
    await database.put(key('marichevy_state_v10'),encoded(raw));
    await database.put(key('marichevy_pending_v10'),encoded('{"old":true}'));await database.del(key('marichevy_pending_v10'));
    await database.put(key('marichevy_session_v10'),encoded('FICTIONAL_TOKEN_MUST_NOT_BE_EXPORTED'));
    await database.put(key('marichevy_state_v10','https://other.invalid'),encoded('FICTIONAL_OTHER_SITE_MUST_NOT_BE_EXPORTED'));
    await database.close();database=null;
    console.log('Самопроверка: read-lock-blocks-writer');
    await macos.withSourceLock(source,async()=>{
      const attempt=contender(path.join(source,'LOCK'));
      try{if(await attempt.result!=='blocked')throw new Error();await attempt.completed;}
      finally{if(attempt.child.exitCode===null)attempt.child.kill();}
    });
    console.log('Самопроверка: writer-blocks-read-lock');
    writer=contender(path.join(source,'LOCK'));
    if(await writer.result!=='locked')throw new Error();
    let rejected=false,entered=false;
    try{await macos.withSourceLock(source,async()=>{entered=true;});}
    catch(error){rejected=error.code==='SOURCE_LOCK_UNAVAILABLE';}
    if(!rejected||entered)throw new Error();
    console.log('Самопроверка: lock-release');
    writer.child.send({type:'release'});await writer.completed;writer=null;
    let enteredAfterRelease=false;
    await macos.withSourceLock(source,async()=>{enteredAfterRelease=true;});
    if(!enteredAfterRelease)throw new Error();
    console.log('Самопроверка: fictional-capture');
    const target=await macos.createPrivateDirectory(root,'capture-');
    const capture=await core.captureProfile({sourceDir:source,outputDir:target,
      withSourceLock:macos.withSourceLock,openDatabase,validateClone,
      makePrivateTemp:macos.createPrivateDirectory});
    const body=await fs.readFile(capture.output_path,'utf8'),value=JSON.parse(body);
    console.log('Самопроверка: fictional-content-check');
    if(value.records.length!==1||value.records[0].key!=='marichevy_state_v10'||value.records[0].raw!==raw||
        body.includes('FICTIONAL_TOKEN')||body.includes('FICTIONAL_OTHER_SITE'))throw new Error();
    if((await fs.stat(capture.output_path)).mode&0o077)throw new Error();
    return true;
  }finally{
    if(writer&&writer.child.exitCode===null)writer.child.kill();
    if(database)try{await database.close();}catch(_){}
    await fs.rm(root,{recursive:true,force:true});
  }
}
async function main(){
  const terminal=readline.createInterface({input:process.stdin,output:process.stdout});let outputDir;
  try{
    console.log('ЧАСТНАЯ КОПИЯ БАНКА — Mac\n');
    console.log('Помощник читает закрытый профиль и сохраняет только финансовые строки finance.marichev.pro.');
    console.log('Пароли и токены не нужны. Данные сайта не меняются и не отправляются в интернет.\n');
    console.log('Перед закрытием браузера сохраните свежий обычный JSON банка. Эта дополнительная копия');
    console.log('читает сохранённые файлы профиля, а не содержимое оперативной памяти открытой вкладки.');
    console.log('В привычном Chrome откройте chrome://version');
    console.log('и скопируйте строку «Путь к профилю». Вставляется путь к папке, а не команда.\n');
    const profile=profilePath(await terminal.question('Путь к профилю: '));
    console.log('\nПолностью завершите Chrome и Яндекс через меню браузера → «Завершить».');
    console.log('Закроется и окно этого чата. Незавершённый ввод сначала сохраните обычной кнопкой банка.');
    await terminal.question('Когда браузеры закрыты, нажмите Enter в этом окне: ');
    await macos.assertBrowserClosed();
    outputDir=await macos.createPrivateDirectory(path.dirname(__dirname),'PRIVATE-backup-');
    console.log('\nПроверяем помощник на вымышленных данных до чтения вашего профиля…');
    try{await selftest(outputDir);}catch(_){throw Object.assign(new Error(),{code:'selftest-failed'});}
    console.log('Встроенная проверка пройдена. Сохраняем частную копию…');
    const result=await core.captureProfile({sourceDir:path.join(profile,'Local Storage','leveldb'),outputDir,
      withSourceLock:macos.withSourceLock,openDatabase,validateClone,makePrivateTemp:macos.createPrivateDirectory});
    const stat=await fs.lstat(result.output_path);
    if(!stat.isFile()||stat.isSymbolicLink()||!stat.size||(stat.mode&0o077))throw new Error();
    console.log('\nСОХРАНЕНО. Частный файл:\n'+result.output_path);
    console.log('\nПоложите его рядом с обычным JSON именно этого Mac-профиля.');
    console.log('В чат напишите «Очередь Mac сохранена». Сам файл оставьте у себя; импортировать его не нужно.');
    return 0;
  }catch(error){
    const code=Object.hasOwn(MESSAGES,error?.code)?error.code:'capture-failed';
    console.log('\nКОПИЯ НЕ ПОДТВЕРЖДЕНА.\n'+MESSAGES[code]+'\nКод: '+code);
    if(outputDir&&code==='clone-cleanup-failed')console.log('Временная частная папка: '+outputDir);
    return 1;
  }finally{terminal.close();}
}
if(require.main===module)main().then(code=>{process.exitCode=code;}).catch(()=>{
  console.log('КОПИЯ НЕ ПОДТВЕРЖДЕНА. Код: capture-failed');process.exitCode=1;
});
module.exports={main,profilePath,openDatabase,_selftestForTests:selftest};
