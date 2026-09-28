import hashlib
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.generics import GenericAPIView
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework import serializers
from .serializers import RegisterSerializer, UserSerializer, LoginSerializer, PasswordSerializer

def rate_limit(request, scope, limit=10):
    email = request.data.get('email', '') if hasattr(request.data, 'get') else ''
    identity = request.META.get('REMOTE_ADDR', '') + ':' + str(email).lower()
    key = 'auth:' + scope + ':' + hashlib.sha256(identity.encode()).hexdigest()
    if cache.add(key, 1, timeout=300):
        return
    if cache.incr(key) > limit:
        raise Throttled(wait=300)

class CsrfSerializer(serializers.Serializer):
    csrfToken = serializers.CharField()

@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = CsrfSerializer
    def get(self, request):
        return Response({'csrfToken': get_token(request)})

@method_decorator(csrf_protect, name='dispatch')
class RegisterView(GenericAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    def post(self, request):
        rate_limit(request, 'register', 5)
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        login(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

@method_decorator(csrf_protect, name='dispatch')
class LoginView(GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rate_limit(request, 'login')
        user = authenticate(request, email=serializer.validated_data['email'].lower(), password=serializer.validated_data['password'])
        if not user:
            raise ValidationError({'credentials': 'Неверный email или пароль'})
        login(request, user)
        return Response(UserSerializer(user).data)

class LogoutView(GenericAPIView):
    serializer_class = UserSerializer
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)

class ProfileView(GenericAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    def get(self, request):
        return Response(UserSerializer(request.user).data)
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

class PasswordView(GenericAPIView):
    serializer_class = PasswordSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data['current_password']):
            raise ValidationError({'current_password': 'Неверный пароль'})
        password = serializer.validated_data['new_password']
        validate_password(password, user)
        user.set_password(password)
        user.save(update_fields=['password'])
        update_session_auth_hash(request, user)
        return Response(status=status.HTTP_204_NO_CONTENT)
