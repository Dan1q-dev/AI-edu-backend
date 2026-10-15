"""DB-backed queue, leased ownership and hard process-tree deadlines."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from django.conf import settings
from django.core.files import File
from django.db import connection, transaction
from django.utils import timezone
from apps.lessons.models import LectureImportJob, LectureImportAsset
from apps.mediafiles.models import MediaFile
from .document import ImportFailure, to_blocks


def lock(query):
    return query.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else query.select_for_update()


@transaction.atomic
def claim():
    now = timezone.now()
    for expired in lock(LectureImportJob.objects.filter(status='RUNNING', lease_expires_at__lt=now))[:100]:
        expired.status = 'PENDING' if expired.attempts < 2 else 'FAILED'
        expired.stage = 'queued' if expired.status == 'PENDING' else 'failed'
        expired.error_code = '' if expired.status == 'PENDING' else 'worker_interrupted'
        expired.lease_token = None
        expired.finished_at = now if expired.status == 'FAILED' else None
        expired.save()
    job = lock(LectureImportJob.objects.filter(status='PENDING').order_by('created_at')).first()
    if not job:
        return None
    job.status, job.stage = 'RUNNING', 'parsing'
    job.attempts += 1
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = now + timedelta(seconds=settings.LECTURE_IMPORT_TIMEOUT + 60)
    job.save()
    return job


def stop_tree(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.wait()


def run_child(job, folder):
    source = Path(folder) / ('source' + Path(job.original_name).suffix.lower())
    with job.source.open('rb') as incoming, source.open('wb') as target:
        shutil.copyfileobj(incoming, target)
    config = {'source': str(source), 'output': folder, 'languages': settings.LECTURE_IMPORT_OCR_LANGUAGES,
              'max_pages': settings.LECTURE_IMPORT_MAX_PAGES, 'force_ocr': job.force_ocr, 'use_ai': job.use_ai,
              'ai': {'base_url': settings.AI_BASE_URL, 'api_key': settings.AI_API_KEY,
                     'model': settings.AI_MODEL, 'timeout': min(settings.AI_TIMEOUT_SECONDS, 60)}}
    process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'apps.lessons.importing.parser'],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               cwd=settings.BASE_DIR, start_new_session=os.name == 'posix')
    try:
        process.stdin.write(json.dumps(config).encode('utf-8'))
        process.stdin.close()
        deadline = time.monotonic() + settings.LECTURE_IMPORT_TIMEOUT
        stage = ''
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise ImportFailure('timeout')
            marker = Path(folder) / 'stage'
            current = marker.read_text(encoding='utf-8') if marker.exists() else 'parsing'
            if current != stage:
                stage = current
                owned = LectureImportJob.objects.filter(pk=job.pk, status='RUNNING', lease_token=job.lease_token).update(stage=stage)
                if not owned:
                    raise ImportFailure('worker_interrupted')
            time.sleep(0.5)
        error = Path(folder) / 'error'
        if error.exists():
            raise ImportFailure(error.read_text(encoding='utf-8')[:50])
        result = Path(folder) / 'result.json'
        if process.returncode or not result.exists():
            raise ImportFailure('processing_failed')
        if result.stat().st_size > 10 * 1024 * 1024:
            raise ImportFailure('document_limit')
        return json.loads(result.read_text(encoding='utf-8'))
    finally:
        if process.poll() is None:
            stop_tree(process)


def store_result(job, result, folder):
    created = []
    try:
        with transaction.atomic():
            owned = LectureImportJob.objects.select_for_update().filter(pk=job.pk, status='RUNNING', lease_token=job.lease_token).first()
            if not owned:
                raise ImportFailure('worker_interrupted')
            image_ids, pages = {}, []
            for asset in result['assets']:
                path = (Path(folder) / asset['file']).resolve()
                if path.parent != Path(folder).resolve() or path.suffix != '.png' or path.stat().st_size > 20 * 1024 * 1024:
                    raise ImportFailure('document_limit')
                media = MediaFile(original_name=path.name, content_type='image/png', size=path.stat().st_size, uploaded_by_id=job.created_by_id)
                with path.open('rb') as stream:
                    media.file.save(path.name, File(stream), save=False)
                created.append(media)
                media.save()
                LectureImportAsset.objects.create(job=job, media=media, key=asset['key'], page=asset.get('page'), is_page=asset['is_page'])
                image_ids[asset['key']] = media.pk
                if asset['is_page']:
                    pages.append({'page': asset['page'], 'url': f'/api/v1/media/{media.pk}/'})
            blocks = to_blocks(result['elements'], image_ids)
            owned.result = {'blocks': blocks, 'pages': pages, 'elements': result['elements'],
                            'warnings': list(dict.fromkeys(result['warnings'])),
                            'stats': {'elements': len(result['elements']), 'images': sum(not a['is_page'] for a in result['assets'])}}
            owned.status, owned.stage = 'SUCCEEDED', 'ready'
            owned.finished_at, owned.lease_token, owned.lease_expires_at = timezone.now(), None, None
            owned.save()
    except Exception:
        for media in created:
            media.file.delete(save=False)
        raise


def execute(job):
    try:
        with TemporaryDirectory(prefix='lecture-import-') as folder:
            result = run_child(job, folder)
            store_result(job, result, folder)
    except Exception as error:
        code = error.code if isinstance(error, ImportFailure) else 'processing_failed'
        LectureImportJob.objects.filter(pk=job.pk, status='RUNNING', lease_token=job.lease_token).update(
            status='FAILED', stage='failed', error_code=code, lease_token=None, lease_expires_at=None, finished_at=timezone.now())
