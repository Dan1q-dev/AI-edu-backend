"""A linear program is derived from real content and server-validated results."""

from django.utils import timezone
from apps.assessments.models import TestAttempt
from .models import LearningItem, UserLearningItemProgress, UserModuleProgress


def module_completion(user, module):
    items = list(module.items.filter(status='PUBLISHED').select_related('test'))
    content = [item for item in items if item.type != 'TEST']
    tests = [item for item in items if item.type == 'TEST' and item.test_id and item.test.is_published]
    completed_ids = set(UserLearningItemProgress.objects.filter(
        user=user, learning_item__in=items, is_completed=True).values_list('learning_item_id', flat=True))
    test = tests[0] if len(tests) == 1 else None
    attempt = (TestAttempt.objects.filter(user=user, test=test.test, test_version=test.test.version)
               .order_by('-completed_at', '-pk').first()) if test else None
    attempts = TestAttempt.objects.filter(user=user, test=test.test, test_version=test.test.version) if test else TestAttempt.objects.none()
    successes = attempts.filter(adaptive_result__module_passed=True) if module.course.adaptive_learning_enabled else attempts.filter(passed=True)
    passed = bool(test and test.test.questions.exists() and successes.exists())
    if module.course.adaptive_learning_enabled:
        passed = passed and UserModuleProgress.objects.filter(user=user, module=module, is_completed=True).exists()
    studied = bool(content) and all(item.pk in completed_ids for item in content)
    return {'completed': studied and passed and bool(test and test.pk in completed_ids),
            'studied': studied, 'content': content, 'completed_ids': completed_ids,
            'test': test, 'passed': passed, 'attempt': attempt}


def certificate_data(certificate):
    if not certificate:
        return None
    return {'token': str(certificate.token), 'number': f'AI-{str(certificate.token).upper()}',
            'learner_name': certificate.learner_name, 'course_title': certificate.course_title,
            'track_title': certificate.track_title, 'hours': certificate.hours,
            'completed_at': certificate.completed_at, 'issued_at': certificate.issued_at,
            'revoked': certificate.revoked_at is not None,
            'download_url': f'/api/v1/certificates/{certificate.token}/download/'}


def course_journey(user, course):
    rows = []
    previous_completed = True
    modules = list(course.modules.order_by('position', 'id'))
    for module in modules:
        state = module_completion(user, module)
        locked = not module.is_published or bool((course.certificate_enabled or course.adaptive_learning_enabled) and not previous_completed)
        content = state['content']
        first = next((item for item in content if item.pk not in state['completed_ids']), next(iter(content), None))
        target = first
        rows.append({'short_id': module.short_id, 'title': module.title, 'is_locked': locked,
                     'is_completed': state['completed'], 'content_completed': state['studied'],
                     'completed_items': len(state['completed_ids'].intersection(item.pk for item in content)),
                     'total_items': len(content),
                     'target_id': target.short_id if target and not locked else None,
                     'test_id': state['test'].short_id if state['test'] and not locked else None,
                     'test_passed': state['passed'],
                     'last_score': state['attempt'].percent if state['attempt'] else None,
                     'passing_percent': state['test'].test.passing_percent if state['test'] else None})
        previous_completed = previous_completed and module.is_published and state['completed']
    completed = sum(row['is_completed'] and not row['is_locked'] for row in rows)
    configured = bool(course.certificate_enabled and len(modules) == course.certificate_module_count
                      and all(module.is_published for module in modules))
    certificate = course.certificates.filter(user=user).first()
    return {'course_id': course.short_id, 'slug': course.slug, 'title': course.title,
            'track_title': course.learning_track.title if course.learning_track_id else '',
            'enabled': course.certificate_enabled, 'hours': course.certificate_hours,
            'required_modules': course.certificate_module_count, 'configured': configured,
            'completed_modules': completed, 'total_modules': len(rows),
            'can_issue': configured and completed == len(rows), 'modules': rows,
            'certificate': certificate_data(certificate), 'as_of': timezone.now()}
