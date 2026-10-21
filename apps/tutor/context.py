import json
import re
from html.parser import HTMLParser

from rest_framework.exceptions import NotFound, ValidationError

from apps.education.access import can_access_item, can_access_lesson
from apps.education.models import LearningItem, Lesson


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4'):
            self.parts.append('\n')
        if tag in ('td', 'th'):
            self.parts.append(' | ')
        if tag == 'img':
            self.parts.append(dict(attrs).get('alt', ''))

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def rich_text(node):
    if not isinstance(node, dict):
        return ''
    if node.get('type') == 'text':
        return str(node.get('text', ''))
    if node.get('type') == 'image':
        attrs = node.get('attrs') or {}
        return str(attrs.get('alt') or attrs.get('title') or '')
    if node.get('type') == 'hardBreak':
        return '\n'
    separator = ' | ' if node.get('type') == 'tableRow' else ''
    value = separator.join(rich_text(child) for child in node.get('content', []))
    if node.get('type') in ('paragraph', 'heading', 'listItem', 'tableRow', 'codeBlock', 'blockquote'):
        value += '\n'
    return value


def block_text(content):
    try:
        node = json.loads(content)
        if isinstance(node, dict) and node.get('type') == 'doc':
            return rich_text(node).strip()
    except (ValueError, TypeError):
        pass
    if not re.search(r'<(?:p|div|table|ul|ol|h[1-6]|span|script|style)\b', content, re.IGNORECASE):
        return content.strip()
    parser = TextParser()
    parser.feed(content)
    return ''.join(parser.parts).strip()


def lesson_context(user, context_type, context_id):
    if context_type == 'item':
        item = LearningItem.objects.select_related('module__course__learning_track', 'lesson').filter(short_id=context_id).first()
        if not item or not can_access_item(user, item):
            raise NotFound()
        if item.type == LearningItem.Type.PRACTICE:
            return practice_context(user, item)
        if item.type != LearningItem.Type.LECTURE or not item.lesson_id:
            raise ValidationError({'detail': 'Тьютор доступен в лекциях и практических работах, но не во время теста.'})
        lesson = item.lesson
    else:
        lesson = Lesson.objects.select_related('module__course__learning_track').filter(short_id=context_id).first()
    if not lesson or not can_access_lesson(user, lesson):
        raise NotFound()
    # Also check the new publication flag when visiting a legacy lesson URL.
    item = LearningItem.objects.filter(lesson=lesson).select_related('module__course__learning_track').first()
    if item and not can_access_item(user, item):
        raise NotFound()
    fragments = []
    for block in lesson.blocks.all():
        text = block_text(block.content)
        if block.type == 'IMAGE':
            text = text or str(block.config.get('alt') or '')
            if text:
                text = f'[Подпись к изображению] {text}'
        if text:
            fragments.append(text)
    if not fragments:
        raise ValidationError({'detail': 'В этой лекции пока нет текста для тьютора.'})
    course = lesson.module.course
    content = '\n\n'.join([f'Курс: {course.title}', f'Модуль: {lesson.module.title}',
                           f'Лекция: {lesson.title}', lesson.description, *fragments])
    if len(content) > 120000:
        raise ValidationError({'detail': 'Материал слишком большой для одного диалога. Разделите лекцию на части.'})
    return lesson, course, content


def practice_context(user, item):
    from apps.activities.services import current_submission
    submission = current_submission(user, item)
    version = submission.practice_version if submission else item.practice_version
    if not version or version.status != 'PUBLISHED':
        raise ValidationError({'detail': 'Практическая работа пока не опубликована.'})
    course = item.module.course
    fragments = [f'Курс: {course.title}', f'Модуль: {item.module.title}',
                 f'Практическая работа: {version.title}', block_text(version.description)]
    # Only student-visible fields; never include reference solutions or test keys.
    for key in ('instructions', 'task', 'description'):
        value = version.config.get(key)
        if isinstance(value, str) and value.strip():
            fragments.append(block_text(value))
    for criterion in version.config.get('criteria', []):
        if isinstance(criterion, dict):
            fragments.append(f"Критерий: {criterion.get('title', '')}. {criterion.get('description', '')}")
    document = getattr(submission, 'workspace_document', None) if submission else None
    if document:
        fragments.append('Текущая работа обучающегося: ' + rich_text(document.content))
    fragments.append('Помогай разобраться с текущим заданием и улучшить решение. Не выполняй итоговое тестирование за пользователя.')
    content = '\n\n'.join(fragment for fragment in fragments if fragment)
    if len(content) > 120000:
        raise ValidationError({'detail': 'Материал практики слишком большой для одного диалога.'})
    return item, course, content
