// Exercises the real persistence/cache modules against disposable server instances.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = require('./load-source.cjs');
const mode = process.argv[2], output = process.argv[3];
const results = [];
function check(name, evidence, condition) {
  assert.ok(condition, name);
  results.push({ name, passed: true, evidence });
}
(async () => {
  if (mode.startsWith('redis')) {
    const cache = source.load('lib/ai/runtime-cache.ts');
    const Redis = source.dependency('ioredis');
    const client = new Redis(process.env.REDIS_URL);
    try {
      assert.equal((await cache.getRuntimeCacheHealth()).status, 'ok');
      const expected = mode==='redis-defaults' ? [120,259200,3888000,600,1209600] : [1,1,1,1,1];
      const keys = [], prefix = process.env.AI_REDIS_PREFIX;
      for (const bucketType of ['minute','day','month']) {
        assert.ok(await cache.incrementCachedQuotaBucket({ apiKeyHash:'synthetic',bucketType,bucketStart:'synthetic',requests:1,tokens:2,costUsd:0.01 }));
        keys.push(`${prefix}:quota:synthetic:${bucketType}:synthetic`);
      }
      assert.ok(await cache.reserveQuotaRequestCache('synthetic','synthetic',3));
      assert.ok(await cache.setJobState('synthetic',{status:'done'}));
      keys.push(`${prefix}:quota:reservation:synthetic`, `${prefix}:job:index:synthetic`);
      const ttl = await Promise.all(keys.map(k=>client.ttl(k)));
      check(mode+'_observed_ttl', { expected_seconds:expected, observed_seconds:ttl }, ttl.every((v,i)=>v>0&&v<=expected[i]&&v>=expected[i]-1));
      if(mode==='redis-expiration') {
        await new Promise(resolve=>setTimeout(resolve,1600));
        const exists = await Promise.all(keys.map(k=>client.exists(k)));
        check('redis_keys_actually_expired', { remaining_keys:exists.reduce((a,b)=>a+b,0) }, exists.every(v=>v===0));
      }
      await client.del(...keys);
    } finally { await client.quit(); }
  } else {
    const db=source.load(`lib/ai/db-${mode}.ts`);
    await db.initAiDatabase();
    let raw, prisma;
    if(mode==='sqlite') {
      const { DatabaseSync }=require('node:sqlite'); raw=new DatabaseSync(process.env.AI_DB_PATH);
    } else { prisma=source.load('lib/ai/prisma.ts').prisma; }
    const now=new Date().toISOString(), old=new Date(Date.now()-31*86400000).toISOString();
    for(const [label,date] of [['expired',old],['fresh',now]]) {
      await db.upsertSession(label,'synthetic',label,date);
      await db.insertMessage({id:label,sessionId:label,role:'user',content:'synthetic '+label,language:'en',createdAt:date});
      await db.createRequestEvent({id:label,sessionId:label,apiKeyHash:'synthetic',route:'/synthetic-retention'});
      if(raw) raw.prepare('UPDATE request_events SET started_at=? WHERE id=?').run(date,label);
      else await prisma.requestEvent.update({where:{id:label},data:{startedAt:new Date(date)}});
      await db.incrementQuotaBucket({apiKeyHash:'synthetic',bucketType:'day',bucketStart:date,requests:1,tokens:1,costUsd:0});
    }
    async function snapshot() {
      if(raw) {
        return Object.fromEntries(['sessions','messages','request_events','quota_counters'].map(t=>[t,raw.prepare(`SELECT COUNT(*) AS n FROM ${t}`).get().n]));
      }
      return {sessions:await prisma.session.count(), messages:await prisma.message.count(),
        request_events:await prisma.requestEvent.count(),quota_counters:await prisma.quotaCounter.count()};
    }
    const before=await snapshot();
    check(mode+'_seeded_old_and_fresh_records',before,Object.values(before).every(n=>n===2));
    for(let i=1;i<25;i++) await db.maybeRunDbMaintenance();
    const beforeTrigger=await snapshot();
    check(mode+'_no_cleanup_before_request_25',beforeTrigger,Object.values(beforeTrigger).every(n=>n===2));
    await db.maybeRunDbMaintenance();
    const after=await snapshot();
    const expired=await db.getHistory('expired'), fresh=await db.getHistory('fresh');
    const expiredRows=Array.isArray(expired)?expired:(expired.messages??expired.items??[]);
    const freshRows=Array.isArray(fresh)?fresh:(fresh.messages??fresh.items??[]);
    check(mode+'_cleanup_removes_expired_preserves_fresh', {before,after,expired_history:expired,fresh_history:fresh},
      Object.values(after).every(n=>n===1)&&expiredRows.length===0&&freshRows.length===1);
    if(raw) raw.close();
    if(prisma) await prisma.$disconnect();
  }
  fs.writeFileSync(output,JSON.stringify({mode,passed:results.length,failed:0,results},null,2));
  process.exit(0);
})().catch(error=>{
  fs.writeFileSync(output,JSON.stringify({mode,passed:results.length,failed:1,results,error:error.message,stack:error.stack},null,2));
  console.error(error); process.exit(1);
});
