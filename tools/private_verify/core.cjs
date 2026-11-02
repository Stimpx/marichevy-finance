'use strict';

// Filesystem- and network-free device comparison. This module does not restore
// a database, acknowledge a queue, authorize a release, merge, or repair data.
const crypto = require('node:crypto');
const STATUS = Object.freeze({ready:true, phase:'device-comparison-only',
  implementation:'exact-decimal-device-comparison', private_inputs_used:false});
const LIMITS = Object.freeze({MAX_FILE:32*1024*1024, MAX_TOTAL:128*1024*1024,
  MAX_FILES:16, MAX_NODES:500000, MAX_DEPTH:64});
const ORIGIN='https://finance.marichev.pro';
const STATE='marichevy_state_v10', PENDING='marichevy_pending_v10';
const BASE=STATE+'_cloud_base_v1', CONFLICT=STATE+'_cloud_conflict_v1';
const BACKUPS=new Set(['marichevy_state_backup_v44','marichevy_pre_import_backup_v73']);
const KEYS=new Set([STATE,PENDING,BASE,CONFLICT,...BACKUPS]);
for(const key of [STATE,PENDING,...BACKUPS]) KEYS.add(key+'_corrupt_v1');
const TABLE_KEYS=Object.freeze({households:['id'], household_members:['household_id','user_id'],
  family_state:['household_id'],family_chore_deliveries:['household_id','chore_id','due_date','chat_id']});
const COLLECTIONS=Object.freeze({entries:'deletedEntries',goals:'deletedGoals',birthdays:'deletedBirthdays',
  boardItems:'deletedBoardItems',chores:'deletedChores',installments:'deletedInstallments'});
const INTELLIGENCE=['budgets','recurring','accounts','favorites'];
const decimals=new WeakSet();
const own=(value,key)=>Object.hasOwn(value,key);
const dict=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&!decimals.has(value)&&!(value instanceof Map);
const get=(value,key,fallback=undefined)=>dict(value)&&own(value,key)?value[key]:fallback;

class InvalidBackup extends Error {
  constructor(code='invalid-backup') { super(code);this.name='InvalidBackup';this.code=code; }
}
function fail(code){throw new InvalidBackup(code);}
function codepoints(value){return [...value].length;}
class ExactDecimal {
  constructor(digits,exponent,negative){
    this.digits=digits.replace(/^0+(?=\d)/,'');
    this.exponent=exponent;
    this.coefficient=BigInt(this.digits)*(negative?-1n:1n);
    decimals.add(this);Object.freeze(this);
  }
}
const decimal=value=>value!==null&&typeof value==='object'&&decimals.has(value);
const digitCache=new Map();
function asciiDigits(text){
  return text.replace(/\p{Decimal_Number}/gu,character=>{
    if(character>='0'&&character<='9') return character;
    if(!digitCache.has(character)){
      const point=character.codePointAt(0);let beginning=point;
      while(beginning>0&&/\p{Decimal_Number}/u.test(String.fromCodePoint(beginning-1))) beginning--;
      digitCache.set(character,String((point-beginning)%10));
    }
    return digitCache.get(character);
  });
}
function number(text){
  if(typeof text!=='string') fail('invalid-number');
  if(codepoints(text)>512) fail('number-size-limit');
  // Decimal(string) accepts Unicode decimal digits, underscores and Python's
  // whitespace set. The JSON parser separately enforces strict JSON tokens.
  const whitespace='[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
  const clean=asciiDigits(text.replace(new RegExp('^'+whitespace+'+|'+whitespace+'+$','g'),'').replace(/_/g,''));
  const match=/^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(clean);
  if(!match) fail('invalid-number');
  const fraction=match[3]===undefined?(match[4]||''):match[3];
  const exponent=BigInt(match[5]||'0')-BigInt(fraction.length);
  if(exponent>1000n||exponent< -1000n) fail('invalid-number');
  return new ExactDecimal((match[2]||'')+fraction,Number(exponent),match[1]==='-');
}
function numberEqual(left,right){
  if(left.coefficient===0n||right.coefficient===0n) return left.coefficient===right.coefficient;
  let a=left.coefficient,b=right.coefficient,ae=left.exponent,be=right.exponent;
  while(a%10n===0n){a/=10n;ae++;}while(b%10n===0n){b/=10n;be++;}
  return a===b&&ae===be;
}
function integerEqual(value,wanted){return decimal(value)&&numberEqual(value,number(String(wanted)));}

function decodeBytes(input){
  let bytes=Buffer.from(input),encoding='utf8',offset=0;
  if(bytes.length>=4&&bytes[0]===0&&bytes[1]===0&&bytes[2]===254&&bytes[3]===255){encoding='utf32be';offset=4;}
  else if(bytes.length>=4&&bytes[0]===255&&bytes[1]===254&&bytes[2]===0&&bytes[3]===0){encoding='utf32le';offset=4;}
  else if(bytes.length>=2&&bytes[0]===254&&bytes[1]===255){encoding='utf16be';offset=2;}
  else if(bytes.length>=2&&bytes[0]===255&&bytes[1]===254){encoding='utf16le';offset=2;}
  else if(bytes.length>=3&&bytes[0]===239&&bytes[1]===187&&bytes[2]===191) offset=3;
  else if(bytes.length>=4){
    if(!bytes[0]) encoding=!bytes[1]?'utf32be':'utf16be';
    else if(!bytes[1]) encoding=bytes[2]||bytes[3]?'utf16le':'utf32le';
  }else if(bytes.length===2){if(!bytes[0])encoding='utf16be';else if(!bytes[1])encoding='utf16le';}
  const chunks=[];let units=[];
  function add(value){units.push(value);if(units.length===4096){chunks.push(String.fromCharCode(...units));units=[];}}
  if(encoding.startsWith('utf16')){
    if((bytes.length-offset)%2)fail('invalid-json');
    for(let i=offset;i<bytes.length;i+=2) add(encoding==='utf16le'?bytes[i]+bytes[i+1]*256:bytes[i]*256+bytes[i+1]);
  }else if(encoding.startsWith('utf32')){
    if((bytes.length-offset)%4)fail('invalid-json');
    for(let i=offset;i<bytes.length;i+=4){
      const point=encoding==='utf32le'?bytes.readUInt32LE(i):bytes.readUInt32BE(i);
      if(point>0x10ffff)fail('invalid-json');
      if(point<=65535)add(point);else{add(0xd800+((point-65536)>>10));add(0xdc00+((point-65536)&1023));}
    }
  }else{
    // Python json.loads(bytes) uses UTF-8 surrogatepass: reject malformed UTF-8
    // but retain an explicitly encoded surrogate for JSON string parity.
    for(let i=offset;i<bytes.length;){
      const first=bytes[i++];if(first<128){add(first);continue;}
      let count,point,min;
      if(first>=194&&first<=223){count=1;point=first&31;min=128;}
      else if(first>=224&&first<=239){count=2;point=first&15;min=2048;}
      else if(first>=240&&first<=244){count=3;point=first&7;min=65536;}
      else fail('invalid-json');
      if(i+count>bytes.length)fail('invalid-json');
      while(count--){const next=bytes[i++];if(next<128||next>191)fail('invalid-json');point=(point<<6)|(next&63);}
      if(point<min||point>0x10ffff)fail('invalid-json');
      if(point<=65535)add(point);else{add(0xd800+((point-65536)>>10));add(0xdc00+((point-65536)&1023));}
    }
  }
  if(units.length)chunks.push(String.fromCharCode(...units));return chunks.join('');
}
function parse(input){
  let raw;
  if(typeof input==='string')raw=input;
  else if(Buffer.isBuffer(input)||input instanceof Uint8Array)raw=decodeBytes(input);
  else fail('invalid-json');
  let position=0,nodes=0;
  const white=()=>{while(position<raw.length&&/[\x20\x09\x0a\x0d]/.test(raw[position]))position++;};
  function string(){
    const start=position++;let closed=false;
    while(position<raw.length){
      const unit=raw.charCodeAt(position++);
      if(unit===34){closed=true;break;}
      if(unit<32)fail('invalid-json');
      if(unit===92){
        const escaped=raw[position++];
        if(escaped==='u'){
          if(!/^[0-9a-fA-F]{4}$/.test(raw.slice(position,position+4)))fail('invalid-json');position+=4;
        }else if(!escaped||!'"\\/bfnrt'.includes(escaped))fail('invalid-json');
      }
    }
    if(!closed)fail('invalid-json');
    try{return JSON.parse(raw.slice(start,position));}catch{fail('invalid-json');}
  }
  function value(depth){
    if(++nodes>LIMITS.MAX_NODES||depth>LIMITS.MAX_DEPTH)fail('json-complexity-limit');
    white();const first=raw[position];
    if(first==='"')return string();
    if(first==='{'){
      position++;white();const result=Object.create(null);
      if(raw[position]==='}'){position++;return result;}
      while(true){
        white();if(raw[position]!=='"')fail('invalid-json');const key=string();white();
        if(raw[position++]!==':')fail('invalid-json');const selected=value(depth+1);
        if(own(result,key))fail('duplicate-json-key');result[key]=selected;white();
        const separator=raw[position++];if(separator==='}')return result;if(separator!==',')fail('invalid-json');
      }
    }
    if(first==='['){
      position++;white();const result=[];
      if(raw[position]===']'){position++;return result;}
      while(true){result.push(value(depth+1));white();const separator=raw[position++];
        if(separator===']')return result;if(separator!==',')fail('invalid-json');}
    }
    for(const [literal,result]of [['true',true],['false',false],['null',null]]){
      if(raw.startsWith(literal,position)){position+=literal.length;return result;}
    }
    if(['NaN','Infinity','-Infinity'].some(literal=>raw.startsWith(literal,position)))fail('invalid-number');
    const token=/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(raw.slice(position));
    if(!token)fail('invalid-json');position+=token[0].length;return number(token[0]);
  }
  const result=value(0);white();if(position!==raw.length)fail('invalid-json');return result;
}
function equal(left,right){
  if(decimal(left)||decimal(right))return decimal(left)&&decimal(right)&&numberEqual(left,right);
  if(left===null||right===null||typeof left!=='object'||typeof right!=='object')return typeof left===typeof right&&left===right;
  if(Array.isArray(left)||Array.isArray(right))return Array.isArray(left)&&Array.isArray(right)&&left.length===right.length&&left.every((item,i)=>equal(item,right[i]));
  if(!dict(left)||!dict(right))return false;
  const keys=Object.keys(left);return keys.length===Object.keys(right).length&&keys.every(key=>own(right,key)&&equal(left[key],right[key]));
}
function identifier(value){
  if(typeof value!=='string'||!value||codepoints(value)>512||/[\x00-\x1f\x7f]/.test(value))fail('invalid-record-id');return value;
}
function uuidValue(value){if(typeof value!=='string'||!(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/).test(value))fail('invalid-scope-id');return value;}
function dated(value){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
  const year=Number(value.slice(0,4)),month=Number(value.slice(5,7)),day=Number(value.slice(8,10));
  if(year<1||month<1||month>12||day<1)return false;
  const days=[31,year%4===0&&(year%100!==0||year%400===0)?29:28,31,30,31,30,31,31,30,31,30,31];return day<=days[month-1];
}
function cents(value){
  try{
    if(typeof value!=='string'&&!decimal(value))return false;
    const amount=typeof value==='string'?number(value):value;
    if(amount.coefficient===0n)return true;
    if(Math.abs(amount.exponent+amount.digits.length-1)>18)return false;
    return amount.exponent>=-2||!/[1-9]/.test(amount.digits.slice(amount.exponent+2));
  }catch(error){if(error instanceof InvalidBackup)return false;throw error;}
}
const identity=parts=>JSON.stringify(parts);
function indexed(rows,keys=['id'],keepDuplicates=false){
  const result=new Map();
  for(const row of rows){
    if(!dict(row))fail('invalid-record');const parts=keys.map(key=>identifier(get(row,key)));let key=identity(parts);
    if(result.has(key)){if(!keepDuplicates)fail('duplicate-record-id');key=identity([...parts,result.size]);}
    result.set(key,row);
  }
  return result;
}
function tombstones(value){
  if(Array.isArray(value)){for(const key of value)identifier(key);}
  else if(dict(value)){for(const [key,at]of Object.entries(value)){identifier(key);if(typeof at!=='string')fail('invalid-tombstones');}}
  else fail('invalid-tombstones');
}
function stateRows(state){
  if(!dict(state)||!Array.isArray(get(state,'entries'))||!dict(get(state,'settings')))fail('invalid-state-shape');
  const result=Object.create(null);
  for(const name of Object.keys(COLLECTIONS)){
    const rows=get(state,name,[]);if(!Array.isArray(rows))fail('invalid-collection');result[name]=indexed(rows,['id'],true);
  }
  const intelligence=get(state,'intelligence',{});if(!dict(intelligence))fail('invalid-collection');
  for(const name of INTELLIGENCE){const rows=get(intelligence,name,[]);if(!Array.isArray(rows))fail('invalid-collection');result['intelligence.'+name]=indexed(rows,['id'],true);}
  for(const row of result.installments.values()){const parts=get(row,'parts',[]);if(!Array.isArray(parts))fail('invalid-collection');indexed(parts,['id'],true);}
  for(const key of Object.values(COLLECTIONS))tombstones(get(state,key,{}));
  const deleted=get(intelligence,'deleted',{});if(!dict(deleted))fail('invalid-tombstones');
  for(const key of INTELLIGENCE)tombstones(get(deleted,key,{}));return result;
}
function truthy(value){
  if(decimal(value))return value.coefficient!==0n;
  if(Array.isArray(value))return value.length!==0;
  if(dict(value))return Object.keys(value).length!==0;return !!value;
}
function contains(container,value){
  if(Array.isArray(container))return container.some(item=>equal(item,value));
  if(dict(container))return typeof value==='string'&&own(container,value);
  if(typeof container==='string')return typeof value==='string'&&container.includes(value);return false;
}
// Every indexed record ID has already been validated as a string. Never pass a
// malformed link value (which may be an exact number or object) to JSON.stringify.
const hasId=(map,id)=>typeof id==='string'&&map.has(identity([id]));
const findId=(map,id)=>typeof id==='string'?map.get(identity([id])):undefined;
function stateHealth(state){
  const rows=stateRows(state);let invalidMoney=0,invalidDates=0,brokenLinks=0;
  let duplicateIds=Object.values(rows).reduce((total,values)=>total+values.size-new Set([...values.values()].map(row=>row.id)).size,0);
  const money=[],dates=[];
  for(const row of rows.entries.values()){money.push(get(row,'amount'));dates.push(get(row,'date'));}
  for(const row of rows.goals.values()){
    for(const key of ['target','saved','monthly'])if(own(row,key))money.push(row[key]);
    const deposits=get(row,'deposits',[]);if(!Array.isArray(deposits))fail('invalid-record');
    for(const deposit of deposits){if(!dict(deposit))fail('invalid-record');if(own(deposit,'amount'))money.push(deposit.amount);if(truthy(get(deposit,'date')))dates.push(deposit.date);}
  }
  for(const row of rows.installments.values()){
    for(const key of ['amount','total'])if(own(row,key))money.push(row[key]);
    const parts=indexed(get(row,'parts',[]),['id'],true);duplicateIds+=parts.size-new Set([...parts.values()].map(part=>part.id)).size;
    for(const part of parts.values()){money.push(get(part,'amount'));dates.push(get(part,'date'));}
    const links=get(row,'links',{});if(!dict(links))fail('invalid-links');
    for(const [partId,entryId]of Object.entries(links))if(!hasId(parts,partId)||!hasId(rows.entries,entryId))brokenLinks++;
  }
  for(const name of INTELLIGENCE)for(const row of rows['intelligence.'+name].values())if(own(row,'amount'))money.push(row.amount);
  for(const row of rows.entries.values()){
    const installmentId=get(row,'installmentId'),partId=get(row,'installmentPartId'),recurringId=get(row,'recurringId'),period=get(row,'recurringPeriod');
    if(truthy(installmentId)){
      const installment=findId(rows.installments,installmentId);const deleted=get(state,'deletedInstallments',{});
      if(!installment&&!contains(deleted,installmentId))brokenLinks++;
      else if(installment&&truthy(partId)&&!hasId(indexed(get(installment,'parts',[]),['id'],true),partId))brokenLinks++;
    }
    if(truthy(recurringId)){
      const deleted=get(get(get(state,'intelligence',{}),'deleted',{}),'recurring',{});
      if(!hasId(rows['intelligence.recurring'],recurringId)&&!contains(deleted,recurringId))brokenLinks++;
    }
    if(truthy(period)&&!(typeof period==='string'&&/^\d{4}-\d{2}$/.test(period)&&dated(period+'-01')))invalidDates++;
  }
  invalidMoney+=money.reduce((total,value)=>total+(!cents(value)?1:0),0);
  invalidDates+=dates.reduce((total,value)=>total+(!dated(value)?1:0),0);
  for(const key of Object.values(COLLECTIONS)){const deleted=get(state,key,{});if(Array.isArray(deleted))duplicateIds+=deleted.length-new Set(deleted).size;}
  return {invalid_cent_values:invalidMoney,invalid_period_values:invalidDates,ambiguous_duplicate_ids:duplicateIds,broken_known_links:brokenLinks,
    records:Object.values(rows).reduce((total,values)=>total+values.size,0)};
}
const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function unpairedSurrogate(text){
  for(let i=0;i<text.length;i++){
    const current=text.charCodeAt(i);
    if(current>=0xd800&&current<=0xdbff){const next=text.charCodeAt(++i);if(!(next>=0xdc00&&next<=0xdfff))return true;}
    else if(current>=0xdc00&&current<=0xdfff)return true;
  }return false;
}
function snapshot(value,project,household){
  if(!dict(value)||value.format!=='marichevy-private-server-backup-v1'||value.read_only!==true)fail('invalid-snapshot-format');
  if(value.project_ref!==project||value.configured_household!==household)fail('foreign-family-or-project');
  if(!integerEqual(value.configured_household_count,1))fail('invalid-snapshot-scope-count');
  const zone=value.database_timezone;
  if(typeof zone!=='string'||!zone||codepoints(zone)>128||/[\x00-\x1f\x7f]/.test(zone))fail('invalid-snapshot-timezone');
  const raw=value.snapshot_json;if(typeof raw!=='string'||unpairedSurrogate(raw))fail('invalid-snapshot-json');
  if(value.snapshot_json_sha256!==digest(Buffer.from(raw,'utf8')))fail('snapshot-json-integrity-mismatch');
  const tables=parse(raw);
  if(!dict(tables)||Object.keys(tables).length!==Object.keys(TABLE_KEYS).length||Object.keys(TABLE_KEYS).some(key=>!own(tables,key)))fail('incomplete-server-table-coverage');
  for(const [name,keys]of Object.entries(TABLE_KEYS)){
    const rows=tables[name];if(!Array.isArray(rows))fail('invalid-table-shape');indexed(rows,keys);
    for(const row of rows)if(get(row,name==='households'?'id':'household_id')!==household)fail('foreign-family-or-project');
  }
  if(tables.family_state.length!==1||tables.households.length!==1||!tables.household_members.length)fail('incomplete-server-table-coverage');
  for(const row of tables.household_members)uuidValue(get(row,'user_id'));
  const state=get(tables.family_state[0],'data');return {tables,state,health:stateHealth(state)};
}
function capture(value,project,household,server,exported){
  if(!dict(value)||value.format!=='marichevy-local-queue-capture-v1'||value.origin!==ORIGIN)fail('invalid-capture-format-or-origin');
  if(value.session_included!==false||value.storage_modified!==false||value.device_clock_verified!==false)fail('invalid-capture-safety-flags');
  const records=value.records;
  if(!Array.isArray(records)||!records.length||!integerEqual(value.key_count,records.length))fail('invalid-capture-records');
  const seen=new Set(),counts={divergent_active_values:0,corrupt_preserved_values:0,conflict_packets:0,pending_values:0};let primarySeen=false;
  if(own(value,'memory_state_json')){
    if(typeof value.memory_state_json!=='string')fail('invalid-memory-state');
    const memory=parse(value.memory_state_json);stateRows(memory);
    if(!equal(memory,server)||!equal(memory,exported))counts.divergent_active_values++;
  }
  for(const row of records){
    if(!dict(row))fail('invalid-capture-records');const key=get(row,'key'),raw=get(row,'raw');
    if(typeof key!=='string'||!(KEYS.has(key)||/^marichevy_state_v10_cloud_conflict_v1_archive_[A-Za-z0-9_-]+$/.test(key))||seen.has(key)||typeof raw!=='string')fail('unexpected-or-duplicate-storage-key');
    seen.add(key);const utf16=Buffer.from(raw,'utf16le'),utf8=Buffer.from(raw,'utf8');
    if(!integerEqual(row.utf16_code_units,utf16.length/2)||!integerEqual(row.utf8_bytes,utf8.length)||row.sha256_utf8!==digest(utf8)||row.sha256_utf16le!==digest(utf16))fail('raw-capture-integrity-mismatch');
    if(key.endsWith('_corrupt_v1')){counts.corrupt_preserved_values++;continue;}
    let parsed;try{parsed=parse(raw);}catch(error){if(!(error instanceof InvalidBackup))throw error;counts.corrupt_preserved_values++;continue;}
    if(key===BASE||key.startsWith(CONFLICT)){
      if(!dict(parsed)||parsed.household!==household)fail('foreign-family-or-project');
      if(key===BASE&&parsed.url!=='https://'+project+'.supabase.co')fail('foreign-family-or-project');
      if(key===BASE)stateRows(get(parsed,'data'));
    }
    if(key.startsWith(CONFLICT))counts.conflict_packets++;
    if(key===STATE||key===PENDING){
      primarySeen=primarySeen||key===STATE;if(key===PENDING)counts.pending_values++;
      stateRows(parsed);if(!equal(parsed,server)||!equal(parsed,exported))counts.divergent_active_values++;
    }else if(BACKUPS.has(key)){
      if(!dict(parsed)||!dict(get(parsed,'data')))counts.corrupt_preserved_values++;else stateRows(parsed.data);
    }
  }
  if(!primarySeen)counts.corrupt_preserved_values++;return counts;
}
function compareDevices(options){
  const report={format:'marichevy-private-device-comparison-v1',phase:'device-comparison-only',outcome:'failed',network_used:false,
    inputs_modified:false,restore_execution_verified:false,release_authorized:false,issues:[],checks:{},counts:{}};
  try{
    if(!dict(options)||options.scopeAttested!==true)fail('private-input-not-authorized');
    const project=options.project,household=uuidValue(options.household);
    if(typeof project!=='string'||!(/^[a-z0-9]{20}$/).test(project))fail('invalid-project-ref');
    const {state,health}=snapshot(options.server,project,household);Object.assign(report.counts,health);
    const devices=options.devices;if(!Array.isArray(devices)||devices.length<2||devices.length>6)fail('both-device-bundles-required');
    report.counts.devices=devices.length;
    for(const device of devices){
      if(!dict(device))fail('invalid-device-plan');
      if(device.scope_verified_by_owner!==true)report.issues.push('device-family-scope-not-attested');
      const exported=device.exported,deviceHealth=stateHealth(exported);
      for(const key of ['invalid_cent_values','invalid_period_values','broken_known_links','ambiguous_duplicate_ids'])report.counts[key]+=deviceHealth[key];
      if(!equal(exported,state))report.issues.push('device-export-diverges');
      const captured=capture(device.captured,project,household,state,exported);
      for(const [key,value]of Object.entries(captured))report.counts[key]=(report.counts[key]||0)+value;
    }
    for(const key of ['invalid_cent_values','invalid_period_values','broken_known_links','ambiguous_duplicate_ids','divergent_active_values','corrupt_preserved_values','conflict_packets'])if(report.counts[key])report.issues.push(key.replace(/_/g,'-'));
    if(report.counts.pending_values)report.issues.push('pending-acknowledgement-required');
    Object.assign(report.checks,{input_scope_and_capture_hashes_valid:true,device_scope_is_owner_attestation:true,
      period_cent_and_known_links_valid:!['invalid_cent_values','invalid_period_values','broken_known_links'].some(key=>report.counts[key]),
      device_variants_match_server:!['device-export-diverges','divergent-active-values','corrupt-preserved-values','conflict-packets'].some(code=>report.issues.includes(code))});
    report.issues=[...new Set(report.issues)].sort();report.outcome=report.issues.length?'review_required':'passed';
  }catch(error){report.issues.push(error instanceof InvalidBackup?error.code:'internal-verifier-error');}
  return report;
}
module.exports=Object.freeze({STATUS,LIMITS,InvalidBackup,parse,number,equal,cents,stateRows,stateHealth,snapshot,capture,compareDevices});
