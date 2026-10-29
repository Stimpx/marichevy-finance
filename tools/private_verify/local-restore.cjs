'use strict';

// Offline, in-memory restore of the four application tables. This is a real
// PostgreSQL 17.5 WASM clone, not a full Supabase/Auth/platform restoration.
// File selection, provenance attestation and secure artifact writes belong to
// the verified owner wrapper. This module never opens any browser profile.
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const core=require('./core.cjs');
const MAX_FILE=32*1024*1024;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PROJECT=/^[a-z0-9]{20}$/;
const ASSETS=Object.freeze({
  'sql-sources.json':['abe00a55653213df3a162cec4387ec1224dd216790114c8da40cb19d2be243ba',21779],
  'pglite/index.cjs':['37ba5965b7042f78b128eaed205ad076153e32468efb2796ddf706feb25e4e06',408401],
  'pglite/pglite.wasm':['8140392c5f70c5aecb40f514db242fce4223cfdd5f37a2b101dbdc30208dc49d',8859436],
  'pglite/pglite.data':['4703ec26f5710abb62db42acad229478b75c51ef7f3bb037286bb2bac139a930',4939155],
  'pglite/package.json':['a540c379fd1d820810793681d25fa7ad5dadfcee2b190d14a6553fdb469cfe3c',5853],
  'pglite/LICENSE':['a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9',10173],
});
const MIGRATIONS=Object.freeze({
  '001_family_state_cas.sql':'a97333d25d903cd013e53973bd5756602756aa0c127effb46814a685e948a7c8',
  '002_restrict_table_capabilities.sql':'2dcc99d29923fae4627201c923327a5ccb07fbd205abf144b8e121e6424d8fb7',
  '003_bound_membership_lookup.sql':'34ee3b3fcae3e5e5b7c7672d17bda3d332d9dea04031e459a493d7ed058e7ea3',
});
const TABLE_KEYS=Object.freeze({households:['id'],household_members:['household_id','user_id'],
  family_state:['household_id'],family_chore_deliveries:['household_id','chore_id','due_date','chat_id']});
const CODES=new Set(['local-restore-invalid-input','local-restore-busy','local-restore-asset-integrity',
  'local-restore-source-mismatch','local-restore-resource-limit','local-restore-invalid-column-type',
  'local-restore-unknown-columns','local-restore-network-forbidden','local-restore-engine-failed',
  'local-restore-rows-differ','local-restore-rls-failed','local-restore-cas-failed',
  'local-restore-close-failed','local-restore-artifact-failed','local-restore-timezone-invalid']);
class LocalRestoreError extends Error {
  constructor(code){const safe=CODES.has(code)?code:'local-restore-engine-failed';super(safe);this.name='LocalRestoreError';this.code=safe;}
}
const fail=code=>{throw new LocalRestoreError(code);};
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const decimalPrototype=Object.getPrototypeOf(core.number('0'));
let running=false;

function assetBytes(relative){
  const pin=ASSETS[relative];if(!pin)fail('local-restore-asset-integrity');
  let fd;
  try{
    // The outer bootstrap validates every ancestor and the complete closure.
    // Recheck the fixed leaf's bytes before any engine import or compilation.
    if(process.platform==='win32'){
      // Windows has no POSIX O_NOFOLLOW. The checked native reader opens the
      // same regular file without following reparse points and denies writes
      // and deletion while reading. Pins are still enforced here, before the
      // engine is imported; callers cannot supply replacement asset bytes.
      const reader=require('./windows-io.cjs');
      const bytes=reader.readCodeFileSync(path.join(__dirname,...relative.split('/')),pin[1]);
      if(!Buffer.isBuffer(bytes)||bytes.length!==pin[1]||sha(bytes)!==pin[0])
        fail('local-restore-asset-integrity');
      return bytes;
    }
    if(typeof fs.constants.O_NOFOLLOW!=='number')fail('local-restore-asset-integrity');
    const filename=path.join(__dirname,...relative.split('/'));
    fd=fs.openSync(filename,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
    const before=fs.fstatSync(fd,{bigint:true});
    if(!before.isFile()||before.nlink!==1n||before.size!==BigInt(pin[1]))fail('local-restore-asset-integrity');
    const bytes=fs.readFileSync(fd),after=fs.fstatSync(fd,{bigint:true});
    if(before.dev!==after.dev||before.ino!==after.ino||before.size!==after.size||before.mtimeNs!==after.mtimeNs||
      before.ctimeNs!==after.ctimeNs||bytes.length!==pin[1]||sha(bytes)!==pin[0])fail('local-restore-asset-integrity');
    return bytes;
  }catch(_){fail('local-restore-asset-integrity');}
  finally{if(fd!==undefined)try{fs.closeSync(fd);}catch(_){fail('local-restore-asset-integrity');}}
}
function trustedSources(){
  const verified=new Map();for(const name of Object.keys(ASSETS))verified.set(name,assetBytes(name));
  const source=JSON.parse(verified.get('sql-sources.json').toString('utf8'));
  for(const [name,digest]of Object.entries(MIGRATIONS))if(typeof source[name]!=='string'||sha(source[name])!==digest)
    fail('local-restore-asset-integrity');
  return {source,verified};
}
function exactInteger(value,bits){
  if(value===null||typeof value!=='object'||Object.getPrototypeOf(value)!==decimalPrototype)return false;
  let integer=value.coefficient;
  if(value.exponent>=0)integer*=10n**BigInt(value.exponent);
  else{const divisor=10n**BigInt(-value.exponent);if(integer%divisor!==0n)return false;integer/=divisor;}
  const limit=1n<<BigInt(bits-1);return integer>=-limit&&integer<limit;
}
function validDate(text){
  if(typeof text!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(text))return false;
  const parsed=new Date(text+'T00:00:00Z');return Number.isFinite(parsed.getTime())&&parsed.toISOString().slice(0,10)===text;
}
function validateColumns(tables,schema){
  for(const [table,columns]of Object.entries(schema))for(const row of tables[table]){
    const names=Object.keys(columns).sort(),actual=Object.keys(row).sort();
    if(names.length!==actual.length||names.some((name,index)=>name!==actual[index]))fail('local-restore-unknown-columns');
    for(const [column,declared]of Object.entries(columns)){
      const value=row[column],nullable=declared.endsWith('?'),kind=nullable?declared.slice(0,-1):declared;
      if(nullable&&value===null)continue;
      let valid=false;
      if(kind==='text')valid=typeof value==='string'&&!value.includes('\0');
      else if(kind==='uuid')valid=typeof value==='string'&&UUID.test(value);
      else if(kind==='json')valid=value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.getPrototypeOf(value)!==decimalPrototype;
      else if(kind==='int'||kind==='bigint')valid=exactInteger(value,kind==='int'?32:64);
      else if(kind==='date')valid=validDate(value);
      else if(kind==='timestamp')valid=typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T[^\0]+(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
      if(!valid)fail('local-restore-invalid-column-type');
    }
  }
}
function boundPostgresReadback(value){
  let bytes=0;
  function visit(item){
    if(item===null)bytes+=4;
    else if(typeof item==='string')bytes+=Buffer.byteLength(JSON.stringify(item));
    else if(typeof item==='boolean')bytes+=5;
    else if(item!==null&&typeof item==='object'&&Object.getPrototypeOf(item)===decimalPrototype){
      const digits=item.digits.length,point=digits+item.exponent;
      const length=(item.coefficient<0n?1:0)+(item.exponent>=0?point:point>0?digits+1:2-point+digits);
      // PostgreSQL emits expanded decimal text. The strict readback parser's
      // number-token limit must remain valid before PostgreSQL allocates it.
      if(length>512)fail('local-restore-resource-limit');bytes+=length;
    }else if(Array.isArray(item)){bytes+=2+2*item.length;for(const child of item)visit(child);}
    else if(item!==null&&typeof item==='object'){
      bytes+=2;for(const [key,child]of Object.entries(item)){bytes+=Buffer.byteLength(JSON.stringify(key))+4;visit(child);}
    }else fail('local-restore-invalid-input');
    if(bytes>MAX_FILE)fail('local-restore-resource-limit');
  }
  visit(value);
}
function rowsEqual(left,right){
  for(const [table,keys]of Object.entries(TABLE_KEYS)){
    if(left[table].length!==right[table].length)return false;
    const rows=new Map(left[table].map(row=>[JSON.stringify(keys.map(key=>row[key])),row]));
    for(const row of right[table]){const key=JSON.stringify(keys.map(name=>row[name]));if(!rows.has(key)||!core.equal(rows.get(key),row))return false;}
  }return true;
}
async function withNetworkDenied(action){
  const saved=[];let attempts=0;
  const denied=()=>{attempts++;fail('local-restore-network-forbidden');};
  function replace(object,key){const descriptor=Object.getOwnPropertyDescriptor(object,key);if(!descriptor)return;
    if(typeof object[key]!=='function')return;saved.push([object,key,descriptor]);Object.defineProperty(object,key,{...descriptor,value:denied});}
  try{
    replace(globalThis,'fetch');
    for(const [module,names]of [
      ['node:http',['request','get']],['node:https',['request','get']],
      ['node:net',['connect','createConnection']],['node:tls',['connect']],['node:dgram',['createSocket']],
      ['node:child_process',['exec','execFile','execSync','execFileSync','spawn','spawnSync','fork']],
    ]){const target=require(module);for(const name of names)replace(target,name);}
    replace(require('node:net').Socket.prototype,'connect');
    const result=await action();if(attempts)fail('local-restore-network-forbidden');return result;
  }finally{for(const [object,key,descriptor]of saved.reverse())Object.defineProperty(object,key,descriptor);}
}
async function one(db,sql,params=[]){const result=await db.query(sql,params);if(result.rows.length!==1)fail('local-restore-engine-failed');return result.rows[0];}
async function visible(db,household,user,role){
  try{
    await db.exec('BEGIN');
    await db.query("SELECT set_config('request.jwt.claim.sub',$1,true),set_config('request.jwt.claim.role',$2,true)",[user,role]);
    await db.exec('SET LOCAL ROLE '+role); // role is one of two fixed internal constants.
    return (await one(db,'SELECT count(*)::text AS count FROM public.family_state WHERE household_id=$1::uuid',[household])).count;
  }finally{await db.exec('ROLLBACK');}
}
async function restoreDatabase({wrapper,tables,project,household,source,verified}){
  let db,result,closed=false;
  try{
    // Every fixed code/SQL/asset leaf was checked before this first import.
    const {PGlite}=require('./pglite/index.cjs');
    db=await PGlite.create('memory://',{debug:0,initialMemory:256*1024*1024,
      wasmModule:await WebAssembly.compile(verified.get('pglite/pglite.wasm')),
      fsBundle:new Blob([verified.get('pglite/pglite.data')])});
    const identity=await one(db,"SELECT current_user AS role,current_setting('server_version_num') AS version,current_setting('transaction_read_only') AS read_only");
    if(identity.role!=='postgres'||identity.version!=='170005'||identity.read_only!=='off')fail('local-restore-engine-failed');
    await db.query("SELECT set_config('TimeZone',$1,false),set_config('DateStyle','ISO, YMD',false),set_config('statement_timeout','30000',false)",[wrapper.database_timezone]);
    await db.exec(source.BOOTSTRAP_SQL);
    await db.exec('BEGIN;CREATE TEMP TABLE restore_payload(value jsonb) ON COMMIT DROP;');
    await db.query('INSERT INTO restore_payload(value) VALUES($1::jsonb)',[wrapper.snapshot_json]);
    await db.exec(source.INSERT_SQL+'\nCOMMIT;');
    const raw=(await one(db,source.READBACK_SQL)).jsonb_build_object;
    if(typeof raw!=='string'||Buffer.byteLength(raw)>MAX_FILE)fail('local-restore-resource-limit');
    const restoredTables=core.parse(raw);if(!rowsEqual(tables,restoredTables))fail('local-restore-rows-differ');
    const member=(await one(db,'SELECT user_id::text AS user_id FROM household_members ORDER BY user_id LIMIT 1')).user_id;
    const outsider=(await one(db,'SELECT gen_random_uuid()::text AS id')).id;
    if((await one(db,'SELECT EXISTS(SELECT 1 FROM household_members WHERE user_id=$1::uuid) AS present',[outsider])).present)fail('local-restore-rls-failed');
    if(await visible(db,household,member,'authenticated')!=='1'||await visible(db,household,outsider,'authenticated')!=='0'||await visible(db,household,outsider,'service_role')!=='1')fail('local-restore-rls-failed');
    for(const name of Object.keys(MIGRATIONS))await db.exec(source[name]);
    if(await visible(db,household,member,'authenticated')!=='1'||await visible(db,household,outsider,'authenticated')!=='0')fail('local-restore-rls-failed');
    try{
      await db.exec('BEGIN;UPDATE public.family_state SET sync_protocol=2;');
      await db.query("SELECT set_config('request.jwt.claim.sub',$1,true),set_config('request.jwt.claim.role','authenticated',true)",[member]);
      await db.exec('SET LOCAL ROLE authenticated');
      const status=(await one(db,"SELECT public.family_state_cas(household_id,sync_revision,data,gen_random_uuid())->>'status' AS status FROM public.family_state")).status;
      if(status!=='written')fail('local-restore-cas-failed');
    }finally{await db.exec('ROLLBACK');}
    const projected=(await one(db,source.READBACK_SQL.replace('to_jsonb(s)',"to_jsonb(s)-'sync_revision'-'sync_protocol'-'last_request_id'"))).jsonb_build_object;
    if(typeof projected!=='string'||Buffer.byteLength(projected)>MAX_FILE)fail('local-restore-resource-limit');
    if(!rowsEqual(tables,core.parse(projected)))fail('local-restore-rows-differ');
    result={raw,engine:'pglite-0.3.14-postgresql-17.5-wasm-in-memory'};
  }finally{
    if(db){try{await db.close();closed=db.closed===true;}catch(_){fail('local-restore-close-failed');}}
    if(db&&!closed)fail('local-restore-close-failed');
  }
  return result;
}
async function restore(options){
  if(running)fail('local-restore-busy');running=true;
  try{
    if(!options||typeof options.backupJson!=='string'||Buffer.byteLength(options.backupJson)>MAX_FILE||
      typeof options.project!=='string'||!PROJECT.test(options.project)||typeof options.household!=='string'||!UUID.test(options.household)||
      typeof options.writePrivateArtifact!=='function')fail('local-restore-invalid-input');
    const wrapper=core.parse(options.backupJson);
    if(!core.equal(wrapper,options.server))fail('local-restore-source-mismatch');
    const {tables,health}=core.snapshot(wrapper,options.project,options.household);
    if(typeof wrapper.database_timezone!=='string'||!/^[A-Za-z0-9_+./:-]{1,100}$/.test(wrapper.database_timezone))fail('local-restore-timezone-invalid');
    const {source,verified}=trustedSources();validateColumns(tables,source.SCHEMA);boundPostgresReadback(tables);
    const result=await withNetworkDenied(()=>restoreDatabase({wrapper,tables,project:options.project,household:options.household,source,verified}));
    // No output callback is invoked until the actual database has closed.
    const sourceDigest=sha(Buffer.from(options.backupJson,'utf8'));
    const readback={format:'marichevy-private-server-backup-v1',captured_at_utc:new Date().toISOString(),
      project_ref:options.project,configured_household:options.household,configured_household_count:1,read_only:true,
      database_timezone:wrapper.database_timezone,query_sha256:sha(source.READBACK_SQL),snapshot_json_sha256:sha(result.raw),
      snapshot_json:result.raw,source_backup_sha256:sourceDigest,restore_scope:'offline-four-app-tables-auth-id-stubs',engine:result.engine};
    const encoded=Buffer.from(JSON.stringify(readback,null,2)+'\n','utf8');
    if(encoded.length>MAX_FILE)fail('local-restore-resource-limit');
    const check=core.snapshot(core.parse(encoded),options.project,options.household);
    if(!rowsEqual(tables,check.tables))fail('local-restore-rows-differ');
    const receipt={format:'marichevy-private-local-restore-receipt-v1',outcome:'passed',engine:result.engine,
      outcome_scope:'four-app-table-restore-only',
      restore_execution_verified:true,release_authorized:false,network_used:false,production_changed:false,original_files_modified:false,
      four_table_roundtrip_verified:true,foreign_keys_and_not_null_restored:true,local_clone_rls_verified:true,minimal_auth_user_stubs_only:true,
      supabase_auth_restored:false,supabase_platform_restored:false,source_unknown_delivery_checks_reproduced:false,
      migration_rehearsal_preserved_original_columns:true,migration_rehearsal_local_cas_verified:true,
      source_file_sha256:sourceDigest,source_digest_scope:'decoded-backup-json-utf8',source_snapshot_json_sha256:wrapper.snapshot_json_sha256,
      readback_file_sha256:sha(encoded),readback_snapshot_json_sha256:sha(result.raw),
      table_counts:Object.fromEntries(Object.entries(tables).map(([table,rows])=>[table,rows.length])),app_health_counts:health,
      app_data_review_required:['invalid_cent_values','invalid_period_values','broken_known_links','ambiguous_duplicate_ids'].some(key=>health[key]>0),
      source_scope_is_owner_attestation:true};
    try{
      await options.writePrivateArtifact('server-restored-PRIVATE.json',encoded);
      await options.writePrivateArtifact('server-restore-receipt-PRIVATE.json',Buffer.from(JSON.stringify(receipt,null,2)+'\n','utf8'));
    }catch(_){fail('local-restore-artifact-failed');}
    return Object.freeze({outcome:'passed',restore_execution_verified:true,release_authorized:false,engine:result.engine});
  }catch(error){
    if(error instanceof LocalRestoreError)throw error;
    // Strict parser codes and PostgreSQL internals can never expose private text.
    if(error instanceof core.InvalidBackup)throw new LocalRestoreError('local-restore-invalid-input');
    throw new LocalRestoreError('local-restore-engine-failed');
  }finally{running=false;}
}
module.exports=Object.freeze({restore,LocalRestoreError,MAX_FILE});
