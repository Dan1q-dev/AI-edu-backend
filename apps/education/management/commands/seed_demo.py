from django.core.management.base import BaseCommand
from apps.education.models import LearningTrack, Module, Lesson
from apps.lessons.models import LessonBlock
from apps.assessments.models import Test, Question, Option

class Command(BaseCommand):
    help = 'Create two demo learning tracks with one sample lesson and test'
    def handle(self, *args, **options):
        tracks = [
            ('it-specialists', 'IT-специалисты', 'Основы технологий и искусственного интеллекта'),
            ('humanities', 'Гуманитарные направления', 'Технологии в гуманитарных исследованиях'),
        ]
        for slug, title, description in tracks:
            track, _ = LearningTrack.objects.get_or_create(slug=slug, defaults={'title': title, 'description': description, 'is_published': True})
            module, _ = Module.objects.get_or_create(track=track, title='Введение', defaults={'description': 'Первые шаги', 'position': 0, 'is_published': True})
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
