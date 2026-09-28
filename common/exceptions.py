from rest_framework.views import exception_handler
from django.http import JsonResponse

def csrf_failure(request, reason=''):
    return JsonResponse({'error': {'code': 'csrf_failed', 'detail': 'CSRF token is missing or invalid'}}, status=403)

def handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {'error': {'code': getattr(exc, 'default_code', 'error'), 'detail': response.data}}
    return response
