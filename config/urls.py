from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.accounts import views as accounts
from apps.education import views as education
from apps.lessons import views as lessons
from apps.assessments import views as assessments
from apps.mediafiles import views as mediafiles

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/v1/csrf/', accounts.CsrfView.as_view()),
    path('api/v1/auth/register/', accounts.RegisterView.as_view()),
    path('api/v1/auth/login/', accounts.LoginView.as_view()),
    path('api/v1/auth/logout/', accounts.LogoutView.as_view()),
    path('api/v1/auth/me/', accounts.ProfileView.as_view()),
    path('api/v1/auth/password/', accounts.PasswordView.as_view()),
    path('api/v1/tracks/', education.TrackList.as_view()),
    path('api/v1/tracks/<int:pk>/', education.TrackDetail.as_view()),
    path('api/v1/modules/', education.ModuleList.as_view()),
    path('api/v1/modules/<int:pk>/', education.ModuleDetail.as_view()),
    path('api/v1/lessons/', education.LessonList.as_view()),
    path('api/v1/lessons/<int:pk>/', education.LessonDetail.as_view()),
    path('api/v1/lessons/<int:pk>/blocks/', lessons.BlocksView.as_view()),
    path('api/v1/lessons/<int:pk>/test/', assessments.TestView.as_view()),
    path('api/v1/tests/<int:pk>/questions/', assessments.QuestionsView.as_view()),
    path('api/v1/lessons/<int:pk>/attempts/', assessments.AttemptView.as_view()),
    path('api/v1/attempts/', assessments.AllAttemptsView.as_view()),
    path('api/v1/media/', mediafiles.MediaUploadView.as_view()),
    path('api/v1/media/<int:pk>/', mediafiles.MediaView.as_view()),
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
