from django.db import transaction
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import Test, Question, Option, TestAttempt

def validate_test(data):
    if not isinstance(data, dict):
        raise ValidationError({'test': 'Ожидается объект'})
    title = str(data.get('title', '')).strip()
    if not title or len(title) > 200:
        raise ValidationError({'title': 'Укажите название до 200 символов'})
    try:
        passing = int(data.get('passing_percent', 70))
    except (TypeError, ValueError):
        raise ValidationError({'passing_percent': 'Ожидается число'})
    if passing < 0 or passing > 100:
        raise ValidationError({'passing_percent': 'Значение от 0 до 100'})
    limit = data.get('max_attempts')
    if limit in ('', None):
        limit = None
    else:
        try: limit = int(limit)
        except (TypeError, ValueError): raise ValidationError({'max_attempts': 'Ожидается число'})
        if limit < 1: raise ValidationError({'max_attempts': 'Минимум одна попытка'})
    questions = data.get('questions', [])
    if not isinstance(questions, list) or len(questions) > 100:
        raise ValidationError({'questions': 'Ожидается список до 100 вопросов'})
    if data.get('is_published') and not questions:
        raise ValidationError({'questions': 'Для публикации нужен хотя бы один вопрос'})
    for qi, q in enumerate(questions):
        if not isinstance(q, dict) or not str(q.get('text', '')).strip() or q.get('position') != qi:
            raise ValidationError({'questions': 'Проверьте текст и порядок вопросов'})
        options = q.get('options', [])
        if not isinstance(options, list) or len(options) < 2 or len(options) > 20:
            raise ValidationError({'options': 'Требуется от 2 до 20 вариантов'})
        if sum(o.get('is_correct') is True for o in options if isinstance(o, dict)) != 1:
            raise ValidationError({'options': 'Ровно один вариант должен быть правильным'})
        try: points = int(q.get('points', 1))
        except (TypeError, ValueError): raise ValidationError({'points': 'Ожидается число'})
        if points < 1 or points > 100: raise ValidationError({'points': 'Баллы от 1 до 100'})
        for oi, o in enumerate(options):
            if not isinstance(o, dict) or not str(o.get('text', '')).strip() or o.get('position') != oi:
                raise ValidationError({'options': 'Проверьте текст и порядок вариантов'})
    return title, passing, limit, questions

@transaction.atomic
def save_test(lesson, data):
    title, passing, limit, questions = validate_test(data)
    test = Test.objects.select_for_update().filter(lesson=lesson).first()
    if test:
        test.version += 1
    else:
        test = Test(lesson=lesson)
    test.title = title
    test.description = str(data.get('description', ''))
    test.passing_percent = passing
    test.max_attempts = limit
    test.is_published = data.get('is_published') is True
    test.save()
    test.questions.all().delete()
    for q in questions:
        question = Question.objects.create(test=test, text=q['text'], position=q['position'], points=int(q.get('points', 1)))
        Option.objects.bulk_create([Option(question=question, text=o['text'], position=o['position'],
            is_correct=o['is_correct']) for o in q['options']])
    return test

@transaction.atomic
def submit_attempt(test_id, user, answers):
    test = Test.objects.select_for_update().select_related('lesson__module__track').get(pk=test_id)
    if not test.is_published or test.lesson.status != 'PUBLISHED' or not test.lesson.module.is_published or not test.lesson.module.track.is_published:
        raise PermissionDenied()
    if test.max_attempts is not None and TestAttempt.objects.filter(test=test, user=user).count() >= test.max_attempts:
        raise ValidationError({'attempts': 'Лимит попыток исчерпан'})
    questions = list(test.questions.prefetch_related('options'))
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise ValidationError({'answers': 'Ответьте на все вопросы'})
    selected = {}
    for item in answers:
        if not isinstance(item, dict) or not isinstance(item.get('question'), int) or not isinstance(item.get('option'), int):
            raise ValidationError({'answers': 'Некорректные ответы'})
        if item['question'] in selected:
            raise ValidationError({'answers': 'Повторяющийся вопрос'})
        selected[item['question']] = item['option']
    if set(selected) != {q.id for q in questions}:
        raise ValidationError({'answers': 'Ответы не соответствуют тесту'})
    earned = total = 0
    snapshot = []
    for q in questions:
        options = list(q.options.all())
        choice = next((o for o in options if o.id == selected[q.id]), None)
        if choice is None:
            raise ValidationError({'answers': 'Вариант не принадлежит вопросу'})
        total += q.points
        earned += q.points if choice.is_correct else 0
        snapshot.append({'question': q.text, 'selected': choice.text, 'correct': next(o.text for o in options if o.is_correct), 'points': q.points})
    percent = round(100 * earned / total, 2) if total else 0
    return TestAttempt.objects.create(test=test, user=user, test_version=test.version,
        answers=answers, snapshot=snapshot, earned_points=earned, total_points=total,
        percent=percent, passed=percent >= test.passing_percent)
