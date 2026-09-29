from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from common.permissions import is_admin
from apps.education.models import Lesson
from .models import Test, TestAttempt
from .serializers import TestAdminSerializer, TestStudentSerializer, QuestionAdminSerializer, QuestionStudentSerializer, AttemptSerializer
from .services import save_test, submit_attempt

class TestView(GenericAPIView):
    serializer_class = TestAdminSerializer
    def get(self, request, short_id):
        lesson = Lesson.objects.filter(short_id=short_id).first()
        if not lesson: raise NotFound()
        test = Test.objects.prefetch_related('questions__options').filter(lesson=lesson).first()
        if not test: raise NotFound()
        if is_admin(request.user):
            return Response(TestAdminSerializer(test).data)
        if not test.is_published or lesson.status != 'PUBLISHED' or not lesson.module.is_published or not lesson.module.track.is_published:
            raise PermissionDenied()
        return Response(TestStudentSerializer(test).data)

    def put(self, request, short_id):
        if not is_admin(request.user): raise PermissionDenied()
        lesson = Lesson.objects.filter(short_id=short_id).first()
        if not lesson: raise NotFound()
        test = save_test(lesson, request.data)
        return Response(TestAdminSerializer(Test.objects.prefetch_related('questions__options').get(pk=test.pk)).data)

class QuestionsView(GenericAPIView):
    serializer_class = QuestionAdminSerializer
    def get(self, request, pk):
        test = Test.objects.select_related('lesson__module__track').prefetch_related('questions__options').filter(pk=pk).first()
        if not test: raise NotFound()
        if is_admin(request.user): return Response(QuestionAdminSerializer(test.questions.all(), many=True).data)
        lesson = test.lesson
        if not test.is_published or lesson.status != 'PUBLISHED' or not lesson.module.is_published or not lesson.module.track.is_published:
            raise PermissionDenied()
        return Response(QuestionStudentSerializer(test.questions.all(), many=True).data)

    def put(self, request, pk):
        if not is_admin(request.user): raise PermissionDenied()
        test = Test.objects.filter(pk=pk).first()
        if not test: raise NotFound()
        updated = save_test(test.lesson, {'title': test.title, 'description': test.description,
            'passing_percent': test.passing_percent, 'max_attempts': test.max_attempts,
            'is_published': test.is_published, 'questions': request.data})
        return Response(QuestionAdminSerializer(updated.questions.prefetch_related('options'), many=True).data)

class AttemptView(GenericAPIView):
    serializer_class = AttemptSerializer
    def get(self, request, short_id):
        test = Test.objects.filter(lesson__short_id=short_id).first()
        if not test: raise NotFound()
        q = TestAttempt.objects.filter(test=test)
        if not is_admin(request.user): q = q.filter(user=request.user)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(q, request)
        return paginator.get_paginated_response(AttemptSerializer(page, many=True).data)

    def post(self, request, short_id):
        test = Test.objects.filter(lesson__short_id=short_id).first()
        if not test: raise NotFound()
        if not isinstance(request.data, dict): raise ValidationError({'answers': 'Ожидается объект'})
        attempt = submit_attempt(test.id, request.user, request.data.get('answers'))
        return Response(AttemptSerializer(attempt).data, status=201)

class AllAttemptsView(GenericAPIView):
    serializer_class = AttemptSerializer
    def get(self, request):
        q = TestAttempt.objects.all() if is_admin(request.user) else TestAttempt.objects.filter(user=request.user)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(q, request)
        return paginator.get_paginated_response(AttemptSerializer(page, many=True).data)
