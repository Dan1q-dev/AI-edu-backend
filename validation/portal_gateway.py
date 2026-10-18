"""Isolated, real-HTTP portal/gateway integration; only the provider is simulated."""
import argparse
import concurrent.futures
from contextlib import closing
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT.parent / 'AI-edu-frontend'
AI = ROOT / 'services/ai-tutor'
PASSWORD = 'SyntheticValidationPassword-2026!'
KEY = 'synthetic-portal-validation-only'
LOCK = threading.Lock()
CALLS = []
ACTIVE = 0
PEAK = 0


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        global ACTIVE, PEAK
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        started = time.time()
        with LOCK:
            ACTIVE += 1
            PEAK = max(PEAK, ACTIVE)
            record = {'path': self.path, 'body': body, 'started_at': started}
            CALLS.append(record)
        try:
            if self.path.endswith('/embeddings'):
                if 'FAULT_RETRIEVAL' in json.dumps(body):
                    self.send_response(503); self.send_header('Content-Type', 'application/json'); self.end_headers()
                    self.wfile.write(b'{"error":{"message":"synthetic retrieval outage","type":"server_error"}}')
                    return
                inputs = body['input'] if isinstance(body['input'], list) else [body['input']]
                data = {'object': 'list', 'model': body['model'], 'data': [
                    {'object': 'embedding', 'index': i, 'embedding': [1.0, 0.0, 0.0]} for i, _ in enumerate(inputs)],
                    'usage': {'prompt_tokens': 1, 'total_tokens': 1}}
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(data).encode()); return
            if not self.path.endswith('/responses'):
                self.send_error(404); return
            encoded = json.dumps(body)
            if 'FAULT_PROVIDER' in encoded:
                self.send_response(503); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(b'{"error":{"message":"synthetic provider outage","type":"server_error"}}'); return
            if 'FAULT_TIMEOUT' in encoded:
                time.sleep(3)
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            scope = 'BETASCOPE' if 'BETASCOPE' in body.get('instructions', '') else 'ALPHASCOPE'
            marker = 'BETASTUDENT' if 'BETASTUDENT' in json.dumps(body.get('input')) else 'ALPHASTUDENT'
            answer = f'{scope} verified {marker}. The lecture rule is scoped to this lesson.'
            def event(kind, data):
                self.wfile.write(('event: '+kind+'\ndata: '+json.dumps({'type': kind, **data})+'\n\n').encode())
                self.wfile.flush()
            event('response.output_text.delta', {'delta': answer})
            if 'FAULT_SILENT_END' in encoded:
                return
            if 'FAULT_BROKEN_STREAM' in encoded:
                self.wfile.write(b'data: {invalid-json}\n\n'); self.wfile.flush(); return
            if 'FAULT_STREAM_STALL' in encoded:
                time.sleep(3); return
            time.sleep(0.35)
            event('response.completed', {'response': {'id': 'synthetic-fixture', 'status': 'completed',
                'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30}}})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            record['finished_at'] = time.time()
            with LOCK:
                ACTIVE -= 1


class ThreadedWSGI(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietWSGI(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def wait_http(url, process=None, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise RuntimeError('Server exited; inspect retained server log')
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 400:
                    return
        except (OSError, urllib.error.HTTPError):
            time.sleep(0.3)
    raise RuntimeError('Server did not become ready: ' + url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    (output / 'screenshots').mkdir()
    report = {'date_utc': datetime.now(timezone.utc).isoformat(), 'provider_mode': 'deterministic local HTTP fixture',
        'real_components': ['Chrome', 'Vite frontend', 'Django session/CSRF/permissions', 'Next.js chat route',
                            'OpenAI SDK transport', 'lesson retrieval', 'SQLite persistence'],
        'not_evaluated': ['live OpenAI provider', 'provider account policy', 'production deployment'], 'results': []}
    processes = []; servers = []; logs = []
    with tempfile.TemporaryDirectory(prefix='aiedu-portal-validation-') as temp:
        temp = Path(temp)
        # Next.js may rewrite tsconfig.json during startup. Run an exact source
        # copy so generated files and configuration changes stay disposable.
        ai_runtime = temp / 'gateway-source'
        shutil.copytree(AI, ai_runtime, ignore=shutil.ignore_patterns('node_modules', '.env*', '.next*', 'data'))
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(ai_runtime/'node_modules'), str(AI/'node_modules')],
                check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            (ai_runtime/'node_modules').symlink_to(AI/'node_modules', target_is_directory=True)
        provider_port, gateway_port, django_port, front_port = [port() for _ in range(4)]
        gateway = f'http://127.0.0.1:{gateway_port}'
        domain = f'http://127.0.0.1:{django_port}'
        base = f'http://127.0.0.1:{front_port}'
        db_path = temp / 'gateway.sqlite'
        def launch(command, cwd, env, name):
            log = (output / name).open('w', encoding='utf-8'); logs.append(log)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            processes.append(process); return process
        def check(name, action):
            started = time.monotonic()
            try:
                evidence = action()
                report['results'].append({'name': name, 'passed': True, 'elapsed_ms': round((time.monotonic()-started)*1000), 'evidence': evidence})
            except Exception as error:
                report['results'].append({'name': name, 'passed': False, 'error': str(error)})
                raise
        def ai_rows():
            with closing(sqlite3.connect(db_path)) as db:
                db.row_factory = sqlite3.Row
                return [dict(row) for row in db.execute('SELECT * FROM request_events ORDER BY started_at')]
        try:
            provider = ThreadingHTTPServer(('127.0.0.1', provider_port), Provider); servers.append(provider)
            threading.Thread(target=provider.serve_forever, daemon=True).start()
            env = os.environ.copy()
            for key in list(env):
                if key.startswith(('OPENAI_', 'AI_', 'API_', 'LOCAL_')) or key in ('DATABASE_URL', 'REDIS_URL'):
                    env.pop(key)
            env.update(OPENAI_API_KEY='synthetic-no-provider-access', OPENAI_BASE_URL=f'http://127.0.0.1:{provider_port}/v1',
                OPENAI_MODEL='synthetic-validation-model', API_SHARED_KEY=KEY, AI_DB_PROVIDER='sqlite',
                AI_DB_PATH=str(db_path), AI_REDIS_ENABLED='false', NEXT_TELEMETRY_DISABLED='1',
                AI_PROVIDER_TIMEOUT_MS='1500', AI_PROVIDER_MAX_RETRIES='0', AI_RPM_LIMIT='1000',
                AI_DAILY_REQUEST_LIMIT='10000', NEXT_DIST_DIR='.next-validation',
                AI_DAILY_TOKEN_LIMIT='10000000', AI_MONTHLY_COST_USD_LIMIT='10000')
            gateway_process = launch(['node', 'node_modules/next/dist/bin/next', 'dev', '-H', '127.0.0.1', '-p', str(gateway_port)], ai_runtime, env, 'gateway.log')
            wait_http(gateway + '/api/health', gateway_process)
            # Warm actual route compilation before measuring the 1500 ms provider deadline.
            try:
                urllib.request.urlopen(urllib.request.Request(gateway+'/api/chat', data=b'{}',
                    headers={'Content-Type': 'application/json', 'X-API-Key': KEY}), timeout=90)
            except urllib.error.HTTPError as error:
                assert error.code == 400
            sys.path.insert(0, str(ROOT))
            os.environ['DEBUG'] = 'true'; os.environ['SECRET_KEY'] = 'isolated-validation-only-secret'
            os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
            for key in ('DATABASE_HOST', 'REDIS_URL', 'S3_ENDPOINT_URL'):
                os.environ.pop(key, None)
            from django.conf import settings
            settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(temp/'domain.sqlite'), 'OPTIONS': {'timeout': 30}}}
            settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
            settings.MEDIA_ROOT = str(temp/'media'); settings.AI_SERVICE_URL = gateway
            settings.AI_SERVICE_API_KEY = KEY; settings.AI_SERVICE_TIMEOUT = 10; settings.AI_TUTOR_RATE = '1000/min'
            import django
            django.setup()
            from django.core.management import call_command
            with (output/'domain setup.log').open('w', encoding='utf-8') as log:
                call_command('migrate', interactive=False, verbosity=1, stdout=log)
            from apps.accounts.models import User
            from apps.education.models import Course, LearningItem, LearningTrack, Lesson, Module
            from apps.lessons.models import LessonBlock
            students = []
            for i, (scope, marker) in enumerate([('ALPHASCOPE','ALPHASTUDENT'), ('BETASCOPE','BETASTUDENT')]):
                track = LearningTrack.objects.create(title=f'Synthetic track {i}', is_published=True)
                course = Course.objects.create(title=f'Synthetic course {i}', learning_track=track, is_published=True)
                module = Module.objects.create(title='Synthetic module', course=course, is_published=True)
                lesson = Lesson.objects.create(title=scope, module=module, status='PUBLISHED')
                text = f'{scope}: The review window is {26+i} hours. This material belongs only to this lecture.'
                LessonBlock.objects.create(lesson=lesson, type='TEXT', content=text, position=0)
                item = LearningItem.objects.create(title=scope, module=module, lesson=lesson, type='LECTURE', status='PUBLISHED', position=0)
                user = User.objects.create_user(email=f'student{i}@synthetic.example', password=PASSWORD, learning_track=track)
                students.append({'id': user.pk, 'email': user.email, 'marker': marker, 'scope': scope,
                    'item': item.short_id, 'lesson': lesson.short_id, 'lesson_pk': lesson.pk, 'course': course.short_id, 'text': text})
            from django.core.wsgi import get_wsgi_application
            server = make_server('127.0.0.1', django_port, get_wsgi_application(), server_class=ThreadedWSGI, handler_class=QuietWSGI)
            servers.append(server); threading.Thread(target=server.serve_forever, daemon=True).start()
            front_env = os.environ.copy(); front_env.update(API_PROXY_TARGET=domain, VITE_LOCAL_AVATAR_ENABLED='false')
            front_process = launch(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(front_port), '--strictPort'], FRONT, front_env, 'frontend.log')
            wait_http(base+'/login', front_process)
            browser_config = {'base': base, 'students': students, 'password': PASSWORD,
                'result': str(output/'browser results.json'), 'screenshots': str(output/'screenshots')}
            config_file = temp/'browser.json'; config_file.write_text(json.dumps(browser_config), encoding='utf-8')
            browser = launch(['node', str(ROOT/'validation/browser.cjs'), str(config_file)], ROOT, os.environ.copy(), 'browser.log')
            browser.wait(timeout=300)
            if (output/'browser results.json').exists():
                report['results'].extend(json.loads((output/'browser results.json').read_text(encoding='utf-8'))['results'])
            if browser.returncode:
                raise RuntimeError('Browser scenario failed; inspect browser.log')
            # Use normal HTTP session login for negative authorization and spoofing cases.
            jar = http.cookiejar.CookieJar(); opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            opener.open(domain+'/api/v1/csrf/').read()
            def post(url, payload, authenticated=True):
                csrf = next((c.value for c in jar if c.name == 'csrftoken'), '')
                req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json','X-CSRFToken':csrf})
                try:
                    response = (opener if authenticated else urllib.request).open(req, timeout=30) if authenticated else urllib.request.urlopen(req, timeout=30)
                except urllib.error.HTTPError as error:
                    response = error
                return response.code, response.read().decode('utf-8')
            assert post(domain+'/api/v1/auth/login/', {'email': students[0]['email'], 'password': PASSWORD})[0] == 200
            import uuid
            payload = {'context_type':'item','context_id':students[0]['item'],'session_id':str(uuid.uuid4()),
                'messages':[{'role':'user','content':'ALPHASTUDENT explain the lecture rule.'}]}
            def denied(name, changes, authenticated=True):
                count = len(ai_rows())
                status, body = post(domain+'/api/v1/tutor/chat/', {**payload, **changes}, authenticated)
                assert status in (403,404), (status,body)
                assert len(ai_rows()) == count
                return {'status':status,'gateway_requests_added':0,'body':body}
            check('foreign_lecture_denied_before_gateway', lambda:denied('foreign',{'context_id':students[1]['item']}))
            check('anonymous_denied_before_gateway', lambda:denied('anonymous',{},False))
            def spoof():
                status, body = post(domain+'/api/v1/tutor/chat/', {**payload, 'user_id':'spoofed', 'course_id':'spoofed',
                    'lesson_content':'SPOOFED_SECRET', 'client_metadata':{'user_id':'spoofed'}})
                assert status == 200 and 'event: done' in body
                row = ai_rows()[-1]; meta = json.loads(row['metadata_json'])
                assert meta['client_metadata']['user_id'] == str(students[0]['id'])
                assert meta['course_id'] == students[0]['course'] and meta['lesson_id'] == students[0]['lesson']
                assert 'SPOOFED_SECRET' not in json.dumps(CALLS)
                return {'status':status,'gateway_metadata':meta,'session':row['session_id'],'spoofed_content_reached_provider':False}
            check('client_identity_and_content_spoofing_ignored', spoof)
            def persistence():
                rows = ai_rows()
                for s in students:
                    own = [r for r in rows if json.loads(r['metadata_json']).get('client_metadata',{}).get('user_id') == str(s['id'])]
                    assert len(own) >= 3
                    for r in own:
                        meta=json.loads(r['metadata_json'])
                        assert meta['course_id']==s['course'] and meta['lesson_id']==s['lesson']
                        assert r['session_id'].startswith(f'platform:{s["id"]}:{s["lesson_pk"]}:')
                successful=[r for r in rows if r['status']==200]
                assert len(successful)>=7
                for r in successful:
                    prompt=json.loads(r['prompt_raw']);who=json.loads(r['metadata_json'])['client_metadata']['user_id']
                    s=next(s for s in students if str(s['id'])==who); other=next(s for s in students if str(s['id'])!=who)
                    assert s['scope'] in prompt['instructions'] and other['scope'] not in json.dumps(prompt)
                    assert other['marker'] not in json.dumps(prompt)
                for r in rows:
                    if r['status']!=200:
                        with closing(sqlite3.connect(db_path)) as db:
                            assert db.execute("SELECT COUNT(*) FROM messages WHERE session_id=? AND role='assistant'",(r['session_id'],)).fetchone()[0]==0
                return {'successful_records':len(successful),'failed_records':len(rows)-len(successful),
                    'user_course_lesson_metadata_match':True,'failed_answers_not_persisted_as_completed':True}
            check('gateway_identity_context_and_persistence', persistence)
            def provider_contract():
                responses=[c for c in CALLS if c['path'].endswith('/responses')]
                assert responses and all(c['body'].get('store') is False for c in responses)
                first_round=responses[:2]
                assert len(first_round)==2
                assert all('round 1' in json.dumps(c['body']) for c in first_round)
                assert max(c['started_at'] for c in first_round)<min(c['finished_at'] for c in first_round)
                return {'store_false_requests':len(responses),'first_round_response_requests_overlap':True,'peak_concurrent_provider_requests':PEAK}
            check('provider_storage_flag_and_real_overlap', provider_contract)
            records=ai_rows()
            # Publish only synthetic data; no cookies, API keys, local database paths or environment dump.
            fields=['session_id','status','started_at','finished_at','metadata_json','prompt_raw','response_raw','retrieval_query','retrieved_chunk_ids']
            (output/'gateway records.json').write_text(json.dumps([{k:r[k] for k in fields} for r in records],ensure_ascii=False,indent=2),encoding='utf-8')
            (output/'provider requests.json').write_text(json.dumps(CALLS,ensure_ascii=False,indent=2),encoding='utf-8')
            report['configuration']={'provider_timeout_ms':1500,'provider_max_retries':0,'database':'fresh temporary SQLite',
                'redis_enabled':False,'provider_store':False,'domain_upstream_timeout_seconds':10}
        except Exception as error:
            report['execution_error']=str(error);traceback.print_exc()
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            for server in servers:
                server.shutdown();server.server_close()
            if 'django' in sys.modules:
                from django.db import connections
                connections.close_all()
            for log in logs: log.close()
            report['passed']=sum(r['passed'] for r in report['results'])
            report['failed']=sum(not r['passed'] for r in report['results']) + int('execution_error' in report)
            report['all_started_processes_stopped']=all(p.poll() is not None for p in processes)
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['passed','failed','all_started_processes_stopped']}))
    return int(bool(report['failed']))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
