"""Starts only fresh, loopback-only retention test services; no production URLs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
AI=ROOT/'services/ai-tutor'


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'date_utc':datetime.now(timezone.utc).isoformat(),'scope':'fresh local test instances; no production configuration verified',
        'provider_account_settings':'NOT_VERIFIED','production_deletion':'NOT_VERIFIED','production_redis_ttl':'NOT_VERIFIED',
        'results':[],'skipped':[]}
    hidden={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    env=os.environ.copy()
    for k in list(env):
        if k.startswith(('AI_','OPENAI_')) or k in ('DATABASE_URL','REDIS_URL'):env.pop(k)
    env.update(AI_TELEMETRY_RETENTION_DAYS='30',AI_DB_CLEANUP_EVERY_REQUESTS='25',AI_REDIS_ENABLED='false')
    with tempfile.TemporaryDirectory(prefix='aiedu-retention-validation-') as tmp:
        tmp=Path(tmp)
        env['AI_DB_PATH']=str(tmp/'sqlite.db')
        def run(mode,extra=None):
            case_env={**env,**(extra or {})}
            with (out/(mode+'.log')).open('w',encoding='utf-8') as log:
                proc=subprocess.run(['node',str(ROOT/'validation/retention.cjs'),mode,str(out/(mode+'.json'))],
                    cwd=AI,env=case_env,stdout=log,stderr=subprocess.STDOUT,timeout=90,**hidden)
            result=json.loads((out/(mode+'.json')).read_text(encoding='utf-8'))
            report['results'].extend(result['results'])
            if proc.returncode:report['results'].append({'name':mode+'_execution','passed':False,'error':result.get('error')})
        run('sqlite')
        pg_bin=Path(os.environ.get('AIEDU_PG_BIN','C:/Program Files/PostgreSQL/18/bin'))
        if (pg_bin/'initdb.exe').exists() or (pg_bin/'initdb').exists():
            def exe(name):return str(pg_bin/(name+('.exe' if os.name=='nt' else '')))
            pg_port=port();pg_data=tmp/'postgres';pg_started=False
            try:
                with (out/'postgres setup.log').open('w',encoding='utf-8') as log:
                    subprocess.run([exe('initdb'),'-D',str(pg_data),'-U','synthetic_validation','--auth=trust','--no-locale','--encoding=UTF8'],check=True,stdout=log,stderr=subprocess.STDOUT,**hidden)
                    subprocess.run([exe('pg_ctl'),'-D',str(pg_data),'-l',str(out/'postgres server.log'),'-o',f'-h 127.0.0.1 -p {pg_port} -F','-w','start'],check=True,stdout=log,stderr=subprocess.STDOUT,**hidden)
                    pg_started=True
                    # Retention uses only sessions/messages/events/quotas. Keep
                    # those tables unchanged; omit the unrelated optional vector
                    # column/index when pgvector is unavailable on this host.
                    schema=(AI/'prisma/schema.prisma').read_text(encoding='utf-8')
                    schema='\n'.join(line for line in schema.splitlines() if 'embedding_vector' not in line)
                    schema_file=tmp/'retention-schema.prisma';schema_file.write_text(schema,encoding='utf-8')
                    report['postgres_schema_scope']='Repository schema with only optional embedding_vector column/index omitted; retention tables unchanged. Not a vector retrieval test.'
                    pg_env={**env,'DATABASE_URL':f'postgresql://synthetic_validation@127.0.0.1:{pg_port}/postgres?schema=public'}
                    subprocess.run(['node','node_modules/prisma/build/index.js','db','push','--schema',str(schema_file),'--skip-generate'],cwd=AI,env=pg_env,check=True,stdout=log,stderr=subprocess.STDOUT,**hidden)
                run('postgres',{'DATABASE_URL':pg_env['DATABASE_URL']})
            finally:
                if pg_started:
                    subprocess.run([exe('pg_ctl'),'-D',str(pg_data),'-m','fast','-w','stop'],check=True,capture_output=True,**hidden)
        else:report['skipped'].append('PostgreSQL binaries unavailable')
        redis=Path(os.environ.get('AIEDU_REDIS_SERVER','redis-server'))
        if redis.is_file() or shutil.which(str(redis)):
            redis_port=port();config=tmp/'redis.conf'
            config.write_text(f'bind 127.0.0.1\nport {redis_port}\nsave ""\nappendonly no\ndir "{tmp.as_posix()}"\n',encoding='utf-8')
            with (out/'redis server.log').open('w',encoding='utf-8') as log:
                server=subprocess.Popen([str(redis),str(config)],stdout=log,stderr=subprocess.STDOUT,**hidden)
                try:
                    for _ in range(100):
                        try:
                            with socket.create_connection(('127.0.0.1',redis_port),timeout=0.1):break
                        except OSError:time.sleep(0.1)
                    redis_env={'REDIS_URL':f'redis://127.0.0.1:{redis_port}/0','AI_REDIS_ENABLED':'true','AI_REDIS_PREFIX':'synthetic-validation'}
                    run('redis-defaults',redis_env)
                    accelerated={k:'1' for k in ['AI_QUOTA_MINUTE_TTL_SEC','AI_QUOTA_DAY_TTL_SEC','AI_QUOTA_MONTH_TTL_SEC','AI_QUOTA_RESERVATION_TTL_SEC','AI_JOB_STATUS_TTL_SEC']}
                    run('redis-expiration',{**redis_env,**accelerated})
                finally:
                    server.terminate();server.wait(timeout=15)
        else:report['skipped'].append('Redis executable unavailable')
    report['passed']=sum(r['passed'] for r in report['results']);report['failed']=sum(not r['passed'] for r in report['results'])
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['passed','failed','skipped']}))
    return int(bool(report['failed']))


if __name__=='__main__':raise SystemExit(main())
