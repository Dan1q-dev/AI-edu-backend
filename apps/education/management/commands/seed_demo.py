from django.core.management.base import BaseCommand
from apps.education.models import LearningTrack, Course, Module, Lesson
from apps.lessons.models import LessonBlock
from apps.assessments.models import Test, Question, Option

class Command(BaseCommand):
    help = 'Create two demo learning tracks with courses, lessons and tests'
    def handle(self, *args, **options):
        tracks = [
            ('IT-специалисты', 'Основы технологий и искусственного интеллекта'),
            ('Гуманитарные науки', 'Технологии в гуманитарных исследованиях'),
        ]
        for title, description in tracks:
            track, _ = LearningTrack.objects.get_or_create(title=title, defaults={'description': description, 'is_published': True, 'is_active': True})
            track.is_active = True
            track.save(update_fields=['is_active'])
            course, _ = Course.objects.get_or_create(learning_track=track, title='Основы искусственного интеллекта', defaults={'description': description, 'is_published': True, 'position': 0})
            module, _ = Module.objects.get_or_create(course=course, title='Введение', defaults={'description': 'Первые шаги', 'position': 0, 'is_published': True})
            lesson, _ = Lesson.objects.get_or_create(module=module, title='Что такое искусственный интеллект?', defaults={'description': 'Знакомство с ИИ', 'position': 0, 'status': 'PUBLISHED'})
            if not lesson.blocks.exists():
                LessonBlock.objects.bulk_create([
                    LessonBlock(lesson=lesson, type='TEXT', position=0, content='# Искусственный интеллект\n\nИИ помогает решать задачи на основе данных.'),
                    LessonBlock(lesson=lesson, type='TEXT', position=1, content='## Где применяется ИИ?\n\n- Образование\n- Исследования\n- Анализ данных'),
                ])
            test, _ = Test.objects.get_or_create(lesson=lesson, defaults={'title': 'Проверка знаний', 'passing_percent': 70, 'is_published': True})
            if not test.questions.exists():
                q = Question.objects.create(test=test, text='Что помогает решать задачи на основе данных?', position=0, points=1)
                Option.objects.bulk_create([Option(question=q, text='Искусственный интеллект', is_correct=True, position=0), Option(question=q, text='Случайный выбор', position=1)])
        self.stdout.write(self.style.SUCCESS('Demo data ready'))
