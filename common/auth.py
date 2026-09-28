from rest_framework.authentication import SessionAuthentication

class CsrfSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        self.enforce_csrf(request)
        return super().authenticate(request)
