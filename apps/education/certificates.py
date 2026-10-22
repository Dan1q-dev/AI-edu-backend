from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.http import FileResponse
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import serializers
from drf_spectacular.utils import extend_schema

from .access import accessible_courses
from .journey import certificate_data, course_journey
from .models import Certificate, UserLearningItemProgress


class CertificateOutput(serializers.Serializer):
    token = serializers.UUIDField()
    number = serializers.CharField()
    learner_name = serializers.CharField()
    course_title = serializers.CharField()
    track_title = serializers.CharField()
    hours = serializers.IntegerField()
    completed_at = serializers.DateTimeField()
    issued_at = serializers.DateTimeField()
    revoked = serializers.BooleanField()
    download_url = serializers.CharField()


class JourneyOutput(serializers.Serializer):
    course_id = serializers.CharField()
    slug = serializers.CharField()
    title = serializers.CharField()
    track_title = serializers.CharField()
    enabled = serializers.BooleanField()
    hours = serializers.IntegerField()
    required_modules = serializers.IntegerField()
    configured = serializers.BooleanField()
    completed_modules = serializers.IntegerField()
    total_modules = serializers.IntegerField()
    can_issue = serializers.BooleanField()
    modules = serializers.ListField(child=serializers.DictField())
    certificate = CertificateOutput(allow_null=True)
    as_of = serializers.DateTimeField()


def student_course(request, slug):
    course = accessible_courses(request.user).filter(short_id=slug).first()
    if not course:
        course = accessible_courses(request.user).filter(slug=slug).first()
    if not course or request.user.role != 'STUDENT':
        raise NotFound()
    return course


class JourneyView(GenericAPIView):
    serializer_class = JourneyOutput
    def get(self, request, slug):
        return Response(course_journey(request.user, student_course(request, slug)))


class IssueCertificateView(GenericAPIView):
    serializer_class = CertificateOutput

    @extend_schema(request=None, responses=CertificateOutput)
    @transaction.atomic
    def post(self, request, slug):
        from apps.accounts.models import User
        User.objects.select_for_update().get(pk=request.user.pk)
        course = student_course(request, slug)
        existing = Certificate.objects.filter(user=request.user, course=course).first()
        if existing:
            if existing.revoked_at:
                raise ValidationError({'detail': 'Сертификат аннулирован. Обратитесь к администратору.'})
            return Response(certificate_data(existing))
        journey = course_journey(request.user, course)
        if not journey['can_issue']:
            raise ValidationError({'detail': 'Сначала завершите все модули программы и сдайте итоговые тесты.'})
        name = ' '.join(part.strip() for part in [request.user.last_name, request.user.first_name] if part.strip())
        if not request.user.first_name.strip() or not request.user.last_name.strip():
            raise ValidationError({'detail': 'Укажите имя и фамилию в профиле перед получением сертификата.'})
        completed_at = UserLearningItemProgress.objects.filter(user=request.user,
            learning_item__module__course=course, is_completed=True).aggregate(latest=Max('completed_at'))['latest']
        certificate = Certificate.objects.create(user=request.user, course=course, learner_name=name,
            course_title=course.title, track_title=journey['track_title'], hours=course.certificate_hours,
            completed_at=completed_at or timezone.now())
        return Response(certificate_data(certificate), status=201)


def public_certificate(token):
    certificate = Certificate.objects.filter(token=token).first()
    if not certificate:
        raise NotFound()
    return certificate


class CertificateView(GenericAPIView):
    serializer_class = CertificateOutput
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        response = Response(certificate_data(public_certificate(token)))
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response


def verification_url(certificate):
    return f'{settings.PUBLIC_SITE_URL}/#/certificates/{certificate.token}'


def certificate_pdf(certificate):
    import qrcode
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph

    font = next((path for path in [Path(settings.CERTIFICATE_FONT_PATH),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), Path('C:/Windows/Fonts/arial.ttf')]
        if str(path) != '.' and path.is_file()), None)
    if not font:
        raise RuntimeError('Certificate Unicode font is not installed')
    if 'CertificateUnicode' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('CertificateUnicode', str(font)))
    buffer = BytesIO()
    width, height = landscape(A4)
    canvas = Canvas(buffer, pagesize=(width, height))
    canvas.setTitle(f'AI Edu - {certificate.learner_name}')
    canvas.setAuthor('AI Edu')
    canvas.setStrokeColor(colors.HexColor('#4058af'))
    canvas.setLineWidth(2)
    canvas.rect(24, 24, width - 48, height - 48)

    def text(value, top, size=16, color='#1e2b44', max_height=48):
        while True:
            style = ParagraphStyle('certificate', fontName='CertificateUnicode', fontSize=size,
                leading=size * 1.3, textColor=colors.HexColor(color), alignment=TA_CENTER)
            paragraph = Paragraph(escape(value), style)
            _, height_used = paragraph.wrap(width - 140, 150)
            if height_used <= max_height or size <= 8:
                break
            size -= 1
        paragraph.drawOn(canvas, 70, height - top - height_used)

    text('AI Edu', 42, 24, '#4058af')
    text('СЕРТИФИКАТ', 98, 30)
    text('об успешном завершении обучения', 148, 14)
    text(certificate.learner_name, 198, 25)
    text(certificate.course_title, 258, 18)
    text(certificate.track_title, 318, 13, '#65728a')
    hours = certificate.hours
    unit = 'час' if hours % 10 == 1 and hours % 100 != 11 else 'часа' if hours % 10 in (2, 3, 4) and hours % 100 not in (12, 13, 14) else 'часов'
    text(f'Объём программы: {hours} {unit}', 354, 16)
    text(f'Дата завершения: {certificate.completed_at:%d.%m.%Y}', 388, 13)
    text(f'Номер: AI-{str(certificate.token).upper()}', 438, 9)
    text('Проверка подлинности и скачивание - по QR-коду', 470, 10, '#65728a')
    qr = qrcode.make(verification_url(certificate))
    qr_buffer = BytesIO()
    qr.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    canvas.drawImage(ImageReader(qr_buffer), width - 132, 42, width=84, height=84)
    canvas.showPage()
    canvas.save()
    buffer.seek(0)
    return buffer


class CertificateDownloadView(CertificateView):
    @extend_schema(responses={(200, 'application/pdf'): bytes})
    def get(self, request, token):
        certificate = public_certificate(token)
        if certificate.revoked_at:
            raise NotFound()
        response = FileResponse(certificate_pdf(certificate), as_attachment=True,
            filename=f'AI-Edu-{certificate.token}.pdf', content_type='application/pdf')
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response


class CertificateQRView(CertificateView):
    @extend_schema(responses={(200, 'image/png'): bytes})
    def get(self, request, token):
        import qrcode
        from django.http import HttpResponse
        certificate = public_certificate(token)
        if certificate.revoked_at:
            raise NotFound()
        output = BytesIO()
        qrcode.make(verification_url(certificate)).save(output, format='PNG')
        return HttpResponse(output.getvalue(), content_type='image/png', headers={'Cache-Control': 'no-store'})
