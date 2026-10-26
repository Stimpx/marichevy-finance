'use strict';

// Darwin filesystem guards. Source LOCK is opened once, read-only. The core
// intentionally excludes LOCK from its source-file list: closing a second FD
// for that inode would release a process-associated POSIX record lock.
const fs = require('node:fs/promises');
const {constants} = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const execFileAsync = promisify(execFile);

const C = Object.freeze({F_SETLK:8,F_RDLCK:1,F_UNLCK:2,F_WRLCK:3,
  SEEK_SET:0,ACL_TYPE_EXTENDED:0x100,ACL_FIRST_ENTRY:0,ACL_NEXT_ENTRY:-1,EINVAL:22,
  ENOENT:2,EACCES:13,EAGAIN:35,MNT_LOCAL:0x1000,MNT_RDONLY:1,MNT_IGNORE_OWNERSHIP:0x00200000});
const SAFE_PARENT_PERMS=BigInt((1<<1)|(1<<3)|(1<<7)|(1<<9)|(1<<11)|(1<<20));
const CODES = new Set(['MAC_UNSUPPORTED','MAC_BINDINGS_UNAVAILABLE','BROWSER_RUNNING',
  'BROWSER_CHECK_FAILED','SOURCE_PATH_UNSAFE','SOURCE_INVALID','SOURCE_LOCK_UNAVAILABLE',
  'SOURCE_LOCK_RELEASE_FAILED','PRIVATE_ACL_UNAVAILABLE','PRIVATE_DIRECTORY_FAILED']);
function failure(code) {
  const value=new Error(code);value.code=code;value.macAdapter=true;return value;
}
function mapped(error,code) { return error?.macAdapter&&CODES.has(error.code)?error:failure(code); }
function localPath(value) {
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||
      Buffer.byteLength(value,'utf8')>1023||/[\x00-\x1f\x7f]/.test(value)||
      value.split('/').some(part=>part==='.'||part==='..'||Buffer.byteLength(part,'utf8')>255))
    throw failure('SOURCE_PATH_UNSAFE');
  return path.posix.normalize(value);
}
function flock(type) {
  // Apple bsd/sys/fcntl.h: off_t, off_t, pid_t, short, short; both supported ABIs.
  const value=Buffer.alloc(24);value.writeInt16LE(type,20);value.writeInt16LE(C.SEEK_SET,22);return value;
}
function identity(stat) { return [stat.dev,stat.ino,stat.uid,stat.nlink].map(String).join(':'); }
function loadNative(arch) {
  try {
    const koffi=require('koffi');
    const lib=koffi.load('/usr/lib/libSystem.B.dylib');
    // fcntl really is variadic; a fixed third pointer has the wrong arm64 ABI.
    const fcntl=lib.func('int fcntl(int fd, int command, ...)');
    const errorPointer=lib.func('int *__error(void)');
    const statfs=lib.func(arch==='arm64'?'statfs':'statfs$INODE64','int',['str','void *']);
    return {
      lock(fd,type) { return fcntl(fd,C.F_SETLK,'void *',flock(type)); },
      errno() { return koffi.decode(errorPointer(),'int'); },
      clearErrno() { koffi.encode(errorPointer(),'int',0); },
      statfs,
      acl_init:lib.func('void *acl_init(int count)'),
      acl_set_fd_np:lib.func('int acl_set_fd_np(int fd, void *acl, int type)'),
      acl_get_fd_np:lib.func('void *acl_get_fd_np(int fd, int type)'),
      acl_get_link_np:lib.func('void *acl_get_link_np(const char *path, int type)'),
      acl_get_entry:lib.func('int acl_get_entry(void *acl, int which, void *entry)'),
      acl_get_tag_type:lib.func('int acl_get_tag_type(void *entry, void *tag)'),
      acl_get_permset_mask_np:lib.func('int acl_get_permset_mask_np(void *entry, void *mask)'),
      acl_valid:lib.func('int acl_valid(void *acl)'),
      acl_free:lib.func('int acl_free(void *acl)'),
    };
  } catch (_) { throw failure('MAC_BINDINGS_UNAVAILABLE'); }
}

function createAdapter(options={}) {
  const platform=options.platform??process.platform,arch=options.arch??process.arch;
  const fsApi=options.fs??fs,uid=options.uid??(()=>process.getuid?.());
  const euid=options.euid??(options.uid?uid:(()=>process.geteuid?.()));
  const run=options.execFile??execFileAsync;
  const randomBytes=options.randomBytes??crypto.randomBytes;
  let bindings=options.native,held=false;
  function native() {
    if(platform!=='darwin'||!['arm64','x64'].includes(arch)||!Number.isSafeInteger(uid())||uid()<=0||euid()!==uid())
      throw failure('MAC_UNSUPPORTED');
    if(!bindings)bindings=loadNative(arch);return bindings;
  }
  function checkVolume(directory,writable=false) {
    const buf=Buffer.alloc(4096);
    if(native().statfs(directory,buf)!==0)throw failure('SOURCE_PATH_UNSAFE');
    // Darwin struct statfs64, not Linux's incompatible statfs layout.
    const type=buf.subarray(72,88).toString('ascii').split('\0',1)[0];
    const flags=buf.readUInt32LE(64);
    if(!['apfs','hfs'].includes(type)||!(flags&C.MNT_LOCAL)||(flags&C.MNT_IGNORE_OWNERSHIP)||
        (writable&&(flags&C.MNT_RDONLY)))
      throw failure('SOURCE_PATH_UNSAFE');
  }
  function checkAncestorAcl(directory) {
    const api=native();let acl;
    try{
      api.clearErrno();acl=api.acl_get_link_np(directory,C.ACL_TYPE_EXTENDED);
      if(acl==null){if(api.errno()!==C.ENOENT)throw failure('SOURCE_PATH_UNSAFE');return;}
      if(api.acl_valid(acl)!==0)throw failure('SOURCE_PATH_UNSAFE');
      const entry=Buffer.alloc(8),tag=Buffer.alloc(4),mask=Buffer.alloc(8);
      for(let index=0;index<=128;index++){
        api.clearErrno();const result=api.acl_get_entry(acl,index?C.ACL_NEXT_ENTRY:C.ACL_FIRST_ENTRY,entry);
        if(result===-1&&api.errno()===C.EINVAL)return;
        if(result!==0||index===128)throw failure('SOURCE_PATH_UNSAFE');
        const pointer=entry.readBigUInt64LE(0);
        if(pointer===0n||api.acl_get_tag_type(pointer,tag)!==0)throw failure('SOURCE_PATH_UNSAFE');
        const kind=tag.readUInt32LE(0);
        if(kind!==1&&kind!==2)throw failure('SOURCE_PATH_UNSAFE');
        if(kind===1){
          if(api.acl_get_permset_mask_np(pointer,mask)!==0||(mask.readBigUInt64LE(0)&~SAFE_PARENT_PERMS)!==0n)
            throw failure('SOURCE_PATH_UNSAFE');
        }
      }
      throw failure('SOURCE_PATH_UNSAFE');
    }finally{if(acl!=null)try{api.acl_free(acl);}catch(_){}}
  }
  async function checkDirectory(value,{owned=false,writable=false}={}) {
    native();const normalized=localPath(value);let current='/';
    const root=await fsApi.lstat('/',{bigint:true});
    if(!root.isDirectory()||root.isSymbolicLink()||![0,uid()].includes(Number(root.uid))||(Number(root.mode)&0o022)!==0)
      throw failure('SOURCE_PATH_UNSAFE');
    checkAncestorAcl('/');
    for(const component of normalized.split('/').filter(Boolean)) {
      current=path.posix.join(current,component);
      const stat=await fsApi.lstat(current,{bigint:true});
      if(!stat.isDirectory()||stat.isSymbolicLink()||![0,uid()].includes(Number(stat.uid))||
          (Number(stat.mode)&0o022)!==0)throw failure('SOURCE_PATH_UNSAFE');
      checkAncestorAcl(current);
    }
    const last=await fsApi.lstat(normalized,{bigint:true});
    if(owned&&Number(last.uid)!==uid())throw failure('SOURCE_PATH_UNSAFE');
    if(await fsApi.realpath(normalized)!==normalized)throw failure('SOURCE_PATH_UNSAFE');
    checkVolume(normalized,writable);return normalized;
  }
  async function checkSource(value) {
    const directory=await checkDirectory(value,{owned:true});
    const entries=await fsApi.readdir(directory,{withFileTypes:true});let found=false;
    for(const item of entries) {
      if(!item||typeof item.name!=='string'||item.name.includes('/')||item.name==='.'||item.name==='..'||
          item.isSymbolicLink()||!item.isFile())throw failure('SOURCE_PATH_UNSAFE');
      const stat=await fsApi.lstat(path.posix.join(directory,item.name),{bigint:true});
      if(!stat.isFile()||stat.isSymbolicLink()||Number(stat.uid)!==uid()||Number(stat.nlink)!==1)
        throw failure('SOURCE_PATH_UNSAFE');
      if(item.name==='LOCK')found=true;
    }
    if(!found)throw failure('SOURCE_LOCK_UNAVAILABLE');return directory;
  }
  async function assertBrowserClosed() {
    native();
    try {
      // Only executable names, never command arguments or process environments.
      const result=await run('/bin/ps',['-A','-ww','-o','comm='],
        {encoding:'utf8',timeout:10000,maxBuffer:4*1024*1024,windowsHide:true});
      if(typeof result?.stdout!=='string'||!result.stdout.trim())throw failure('BROWSER_CHECK_FAILED');
      for(const text of result.stdout.split('\n')) {
        const executable=text.trim(),name=path.posix.basename(executable);
        const browserCrashpad=/^chrome_crashpad_handler$/i.test(name)&&
          /\/(?:Google Chrome(?: Beta| Dev| Canary)?|Chromium|Yandex(?: Browser)?)\.app\//i.test(executable);
        if(/^(?:Google Chrome|Chromium|Yandex|Yandex Browser)(?:$|[ (])/i.test(name)||
            browserCrashpad)throw failure('BROWSER_RUNNING');
      }
    }catch(error){throw mapped(error,'BROWSER_CHECK_FAILED');}
  }
  async function withSourceLock(leveldbDir,fn) {
    const api=native();let handle,initial,callbackStarted=false,thrown;
    // Reserve before the first await, including during browser/path checks. A
    // nested/concurrent call must not open/close another FD to the same inode.
    if(held||typeof fn!=='function')throw failure('SOURCE_INVALID');
    held=true;
    try {
      await assertBrowserClosed();const directory=await checkSource(leveldbDir);
      const lock=path.posix.join(directory,'LOCK');initial=await fsApi.lstat(lock,{bigint:true});
      handle=await fsApi.open(lock,constants.O_RDONLY|constants.O_NOFOLLOW);
      const opened=await handle.stat({bigint:true});
      if(!opened.isFile()||Number(opened.uid)!==uid()||Number(opened.nlink)!==1||identity(opened)!==identity(initial))
        throw failure('SOURCE_PATH_UNSAFE');
      if(api.lock(handle.fd,C.F_RDLCK)!==0)throw failure('SOURCE_LOCK_UNAVAILABLE');
      await assertBrowserClosed();await checkSource(directory);
      if(identity(await fsApi.lstat(lock,{bigint:true}))!==identity(initial))throw failure('SOURCE_PATH_UNSAFE');
      callbackStarted=true;const result=await fn();
      if(identity(await handle.stat({bigint:true}))!==identity(initial)||
          identity(await fsApi.lstat(lock,{bigint:true}))!==identity(initial))throw failure('SOURCE_PATH_UNSAFE');
      return result;
    }catch(error){thrown=error;if(callbackStarted)throw error;throw mapped(error,'SOURCE_INVALID');}
    finally {
      if(!handle)held=false;
      else {
        // close releases our read lock. Never open another FD for this LOCK.
        // Keep the reservation until async close has completed. On an unknown
        // close outcome, fail closed against any retry in this process.
        try{await handle.close();held=false;}catch(_){if(!thrown)throw failure('SOURCE_LOCK_RELEASE_FAILED');}
      }
    }
  }
  async function createPrivateDirectory(parent,prefix) {
    const api=native();let destination,handle,empty,checked;
    try {
      if(typeof prefix!=='string'||!/^[a-z0-9_-][a-z0-9._-]{0,63}$/i.test(prefix))
        throw failure('PRIVATE_DIRECTORY_FAILED');
      const root=await checkDirectory(parent,{owned:true,writable:true});
      for(let attempt=0;attempt<8;attempt++) {
        const candidate=path.posix.join(root,prefix+randomBytes(12).toString('hex'));
        try{await fsApi.mkdir(candidate,{mode:0o700});destination=candidate;break;}
        catch(error){if(error?.code!=='EEXIST')throw error;}
      }
      if(!destination)throw failure('PRIVATE_DIRECTORY_FAILED');
      // No private content exists yet. Remove inherited ACLs ONLY on this newly
      // created, owner-controlled directory before placing any source clone.
      const before=await fsApi.lstat(destination,{bigint:true});
      handle=await fsApi.open(destination,constants.O_RDONLY|constants.O_NOFOLLOW);
      if(identity(await handle.stat({bigint:true}))!==identity(before)||Number(before.uid)!==uid()||!before.isDirectory())
        throw failure('PRIVATE_ACL_UNAVAILABLE');
      empty=api.acl_init(0);
      if(empty==null||api.acl_valid(empty)!==0||api.acl_set_fd_np(handle.fd,empty,C.ACL_TYPE_EXTENDED)!==0)
        throw failure('PRIVATE_ACL_UNAVAILABLE');
      await handle.chmod(0o700);
      api.clearErrno();checked=api.acl_get_fd_np(handle.fd,C.ACL_TYPE_EXTENDED);
      if(checked==null) {
        if(api.errno()!==C.ENOENT)throw failure('PRIVATE_ACL_UNAVAILABLE');
      }else{
        if(api.acl_valid(checked)!==0)throw failure('PRIVATE_ACL_UNAVAILABLE');
        const entry=Buffer.alloc(8);api.clearErrno();
        if(api.acl_get_entry(checked,C.ACL_FIRST_ENTRY,entry)!==-1||api.errno()!==C.EINVAL)
          throw failure('PRIVATE_ACL_UNAVAILABLE');
      }
      const after=await handle.stat({bigint:true});
      if(!after.isDirectory()||Number(after.uid)!==uid()||(Number(after.mode)&0o777)!==0o700||
          identity(after)!==identity(before)||identity(await fsApi.lstat(destination,{bigint:true}))!==identity(before))
        throw failure('PRIVATE_ACL_UNAVAILABLE');
      await checkDirectory(destination,{owned:true,writable:true});return destination;
    }catch(error){
      // The new empty directory may remain on failure. Never recursively delete
      // an unverified path or modify a pre-existing owner directory.
      throw mapped(error,'PRIVATE_DIRECTORY_FAILED');
    }finally{
      if(checked!=null)try{api.acl_free(checked);}catch(_){}
      if(empty!=null)try{api.acl_free(empty);}catch(_){}
      if(handle)try{await handle.close();}catch(_){}
    }
  }
  return Object.freeze({assertBrowserClosed,withSourceLock,createPrivateDirectory});
}

// A separate process is essential: POSIX locks from the same process can merge
// or replace one another, so an in-process writer is not a valid exclusion test.
async function selftestContender() {
  let handle,api,released=false;
  const finish=async(code)=>{
    if(released)return;released=true;
    try{if(handle)await handle.close();}catch(_){code=1;}
    process.exitCode=code;if(process.connected)process.disconnect();
  };
  const timer=setTimeout(()=>finish(1),30000);timer.unref();
  process.once('disconnect',()=>finish(1));
  process.once('message',async message=>{
    try{
      if(process.platform!=='darwin'||!['x64','arm64'].includes(process.arch)||
          message?.type!=='try-writer'||typeof message.filename!=='string')throw new Error();
      api=loadNative(process.arch);
      handle=await fs.open(localPath(message.filename),constants.O_RDWR|constants.O_NOFOLLOW);
      const stat=await handle.stat();
      if(!stat.isFile()||stat.uid!==process.getuid()||stat.nlink!==1)throw new Error();
      const outcome=api.lock(handle.fd,C.F_WRLCK);
      if(outcome!==0){const code=api.errno();if(![C.EACCES,C.EAGAIN].includes(code))throw new Error();
        process.send?.({outcome:'blocked'});await finish(0);return;}
      process.send?.({outcome:'locked'});
      process.once('message',message=>finish(message?.type==='release'?0:1));
    }catch(_){process.send?.({outcome:'failed'});await finish(1);}
  });
}
if(require.main===module){
  if(process.argv.length===3&&process.argv[2]==='--selftest-contender'&&process.send)selftestContender();
  else process.exitCode=1;
}
module.exports={...createAdapter(),_createAdapterForTests:createAdapter,_localPathForTests:localPath,
  _flockForTests:flock};
