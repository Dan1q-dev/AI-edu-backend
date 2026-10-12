"""Read-only learning summaries derived from the existing progress records."""

from collections import defaultdict
from django.db.models import Max

from apps.assessments.models import TestAttempt
from .adaptive import module_states
from .models import LearningItem, Module, PracticeSubmission, UserLearningItemProgress, UserModuleProgress


def learning_summaries(user, courses):
    courses = list(courses)
    course_ids = [course.pk for course in courses]
    modules = list(Module.objects.filter(course_id__in=course_ids, is_published=True).order_by('position', 'id'))
    items = list(LearningItem.objects.filter(module_id__in=[module.pk for module in modules], status='PUBLISHED', module__course__is_published=True)
                 .select_related('module').order_by('module__position', 'module_id', 'position', 'id'))
    item_ids = [item.pk for item in items]
    progress = {row.learning_item_id: row for row in UserLearningItemProgress.objects.filter(user=user, learning_item_id__in=item_ids)}
    module_progress = {row.module_id: row for row in UserModuleProgress.objects.filter(user=user, module_id__in=[module.pk for module in modules])}
    activity = {item_id: row.updated_at for item_id, row in progress.items()}
    for item_id, updated_at in PracticeSubmission.objects.filter(user=user, item_id__in=item_ids).values_list('item_id', 'updated_at'):
        activity[item_id] = max(activity.get(item_id, updated_at), updated_at)
    # Failed attempts also mean a course was started, without completing its test.
    latest_attempts = TestAttempt.objects.filter(user=user, test__learning_item__id__in=item_ids).order_by().values('test__learning_item__id').annotate(last_activity=Max('completed_at'))
    for entry in latest_attempts:
        item_id, completed_at = entry['test__learning_item__id'], entry['last_activity']
        activity[item_id] = max(activity.get(item_id, completed_at), completed_at)

    modules_by_course, items_by_course = defaultdict(list), defaultdict(list)
    for module in modules:
        modules_by_course[module.course_id].append(module)
    for item in items:
        items_by_course[item.module.course_id].append(item)
    results = []
    for course in courses:
        course_modules = modules_by_course[course.pk]
        states = module_states(user, course, modules=course_modules,
                               progress_rows=[module_progress[module.pk] for module in course_modules if module.pk in module_progress])
        members = items_by_course[course.pk]
        completed_count = sum(bool(progress.get(item.pk) and progress[item.pk].is_completed) for item in members)
        completed = bool(members) and completed_count == len(members)
        available = [item for item in members if not states[item.module.short_id]['is_locked']]
        unfinished = [item for item in available if not (progress.get(item.pk) and progress[item.pk].is_completed)]
        in_progress = [item for item in unfinished if progress.get(item.pk) and progress[item.pk].progress_percent > 0]
        resume = max(in_progress, key=lambda item: (progress[item.pk].updated_at, item.pk)) if in_progress else next(iter(unfinished), None)
        last_activity = max((activity[item.pk] for item in members if item.pk in activity), default=None)
        results.append({
            'id': course.pk, 'short_id': course.short_id, 'slug': course.slug, 'title': course.title,
            'description': course.description, 'cover': course.cover_id,
            'learning_track_title': course.learning_track.title if course.learning_track_id else None,
            'percent': 100 if completed else min(99, round(sum(progress[item.pk].progress_percent for item in members if item.pk in progress) / len(members))) if members else 0,
            'completed_items': completed_count, 'total_items': len(members),
            'is_started': last_activity is not None, 'is_completed': completed, 'last_activity_at': last_activity,
            'resume_learning_item': {'short_id': resume.short_id, 'title': resume.title, 'type': resume.type} if resume and not completed else None,
            'items': {item.short_id: {'progress_percent': progress[item.pk].progress_percent if item.pk in progress else 0,
                                    'is_completed': bool(progress.get(item.pk) and progress[item.pk].is_completed), 'is_started': True}
                      for item in members if item.pk in activity},
            'modules': states,
        })
    return results


def learning_dashboard(user, courses):
    summaries = learning_summaries(user, courses)
    # Keep the dashboard payload compact; item details belong to course progress.
    for summary in summaries:
        summary.pop('items')
        summary.pop('modules')
    started = sorted((entry for entry in summaries if entry['is_started']), key=lambda entry: entry['last_activity_at'], reverse=True)
    active = [entry for entry in started if not entry['is_completed']]
    return {'resume_course': next(iter(active), None), 'active_courses': active,
            'completed_courses': [entry for entry in started if entry['is_completed']],
            'available_courses': [entry for entry in summaries if not entry['is_started']]}
