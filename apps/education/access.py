from common.permissions import is_admin

def can_access_lesson(user, lesson):
    if is_admin(user):
        return True
    course = lesson.module.course
    track = course.learning_track
    return bool(lesson.status == 'PUBLISHED' and lesson.module.is_published and course.is_published
                and track and track.is_published and track.is_active
                and user.is_authenticated and user.learning_track_id == track.pk)
