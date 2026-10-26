'use strict';

// Executed on the owner's Windows before touching the selected real profile.
// All rows here are intentionally fictional and the temporary fixtures are
// removed. It tests the shipped native modules and actual Windows lock API.
const fs = require('node:fs/promises');
const path = require('node:path');
const {ClassicLevel} = require('classic-level');
const core = require('./capture.cjs');

const fail = () => { throw new Error('selftest-failed'); };
const encoded = text => Buffer.concat([Buffer.from([0]),Buffer.from(text,'utf16le')]);
const key = (name, origin=core.ORIGIN) => Buffer.concat([Buffer.from('_'+origin+'\0'),Buffer.from([1]),Buffer.from(name,'latin1')]);

async function selftest({outputDir, windows, openDatabase, validateClone}) {
  const root = await windows.createPrivateDirectory(outputDir, 'selftest-');
  let database;
  try {
    const storage=path.join(root,'fictional-profile','Local Storage','leveldb');
    await fs.mkdir(storage,{recursive:true,mode:0o700});
    database=new ClassicLevel(storage,{keyEncoding:'buffer',valueEncoding:'buffer'});
    await database.open();
    const raw='{"entries":[],"note":"Только учебная проверка","exact":9007199254740993}';
    await database.put(key('marichevy_state_v10'),encoded(raw));
    await database.put(key('marichevy_pending_v10'),encoded('{"old":true}'));
    await database.del(key('marichevy_pending_v10'));
    await database.put(key('marichevy_session_v10'),encoded('FICTIONAL_TOKEN_MUST_NOT_BE_EXPORTED'));
    await database.put(key('marichevy_state_v10','https://other.invalid'),encoded('FICTIONAL_OTHER_SITE_MUST_NOT_BE_EXPORTED'));
    await database.close();database=null;
    let lockRejected=false, attempted;
    await windows.withSourceLock(storage,async()=>{
      attempted=new ClassicLevel(storage,{createIfMissing:false,keyEncoding:'buffer',valueEncoding:'buffer'});
      try { await attempted.open(); }
      catch (_) { lockRejected=true; }
      finally { try { await attempted.close(); } catch (_) {} }
    });
    if (!lockRejected) fail();
    const target=path.join(root,'capture');await fs.mkdir(target,{mode:0o700});
    const capture=await core.captureProfile({sourceDir:storage,outputDir:target,
      withSourceLock:windows.withSourceLock,openDatabase,validateClone,
      makePrivateTemp:windows.createPrivateDirectory});
    const body=await fs.readFile(capture.output_path,'utf8');
    const value=JSON.parse(body);
    if (value.records.length!==1 || value.records[0].key!=='marichevy_state_v10' || value.records[0].raw!==raw
        || body.includes('FICTIONAL_TOKEN') || body.includes('FICTIONAL_OTHER_SITE')) fail();
    return true;
  } finally {
    if (database) try { await database.close(); } catch (_) {}
    await fs.rm(root,{recursive:true,force:true});
  }
}

module.exports={selftest};
