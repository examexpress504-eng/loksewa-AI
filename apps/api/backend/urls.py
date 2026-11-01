from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
)
from core.serializers import CustomTokenObtainPairSerializer

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

from core.views import (
    UserMeView, AdminLoginView, AuthLogoutView, ForgotPasswordView,
    ResetPasswordConfirmView, StudentSignupView, SignupRequestOTPView,
    VerifyEmailOTPView, VerifyRecoveryCodeView, StudentDashboardView,
    StudentPackageStatusView, SocialLoginView, CompleteGoogleProfileView,
    CustomTokenRefreshView,
)
from core.media_views import drive_media_proxy
from core.feedback_views import StudentFeedbackListView
from core.teacher_views import (
    TeacherProfileView,
    TeacherAvatarUploadView,
    TeacherChangePasswordView,
    TeacherPreferencesView,
)
from core.two_factor_views import (
    TwoFactorStatusView,
    TwoFactorSetupView,
    TwoFactorVerifySetupView,
    TwoFactorDisableView,
    TwoFactorLoginView,
)
from ai_tutor.views import AITutorEndpointView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/me/', UserMeView.as_view(), name='auth_me'),
    path('api/auth/signup/', StudentSignupView.as_view(), name='auth_student_signup'),
    path('api/auth/signup/request-otp/', SignupRequestOTPView.as_view(), name='auth_signup_request_otp'),
    path('api/auth/verify-email-otp/', VerifyEmailOTPView.as_view(), name='auth_verify_email_otp'),
    path('api/auth/verify-recovery-code/', VerifyRecoveryCodeView.as_view(), name='auth_verify_recovery_code'),
    path('api/auth/social/', SocialLoginView.as_view(), name='auth_social_login'),
    path('api/auth/complete-profile/', CompleteGoogleProfileView.as_view(), name='auth_complete_google_profile'),
    path('api/auth/admin-login/', AdminLoginView.as_view(), name='auth_admin_login'),
    path('api/auth/logout/', AuthLogoutView.as_view(), name='auth_logout'),
    path('api/auth/forgot-password/', ForgotPasswordView.as_view(), name='auth_forgot_password'),
    path('api/auth/reset-password/', ResetPasswordConfirmView.as_view(), name='auth_reset_password_confirm'),
    path('api/auth/2fa/status/', TwoFactorStatusView.as_view(), name='auth_2fa_status'),
    path('api/auth/2fa/setup/', TwoFactorSetupView.as_view(), name='auth_2fa_setup'),
    path('api/auth/2fa/verify-setup/', TwoFactorVerifySetupView.as_view(), name='auth_2fa_verify_setup'),
    path('api/auth/2fa/disable/', TwoFactorDisableView.as_view(), name='auth_2fa_disable'),
    path('api/auth/2fa/login/', TwoFactorLoginView.as_view(), name='auth_2fa_login'),
    path('api/dashboard/', StudentDashboardView.as_view(), name='student_dashboard'),
    path('api/dashboard/package-status/', StudentPackageStatusView.as_view(), name='student_package_status'),
    path('api/media/drive/<str:file_id>/', drive_media_proxy, name='drive_media_proxy'),
    path('api/student/feedback/', StudentFeedbackListView.as_view(), name='student_feedback_list'),

    # Teacher self-service settings
    path('api/auth/teacher/profile/', TeacherProfileView.as_view(), name='teacher_profile'),
    path('api/auth/teacher/avatar/', TeacherAvatarUploadView.as_view(), name='teacher_avatar'),
    path('api/auth/teacher/change-password/', TeacherChangePasswordView.as_view(), name='teacher_change_password'),
    path('api/auth/teacher/preferences/', TeacherPreferencesView.as_view(), name='teacher_preferences'),

    path('api/', include('exams.urls')),
    path('api/analytics/', include('analytics.urls')),
    path('api/notes/', include('notes.urls')),
    path('api/marketplace/', include('marketplace.urls')),
    path('marketplace/', include('marketplace.urls')),
    path('api/games/', include('games.urls')),
    path('api/study-plan/', include('study_plan.urls')),
    path('api/admin/', include('administration.urls')),
    path('api/tutor/', include('ai_tutor.urls')),
    path('api/ai/tutor/', AITutorEndpointView.as_view(), name='ai_tutor_api_endpoint'),
    path('api/support/', include('support.urls')),
    path('api/student/', include('support.student_urls')),
    path('api/subscriptions/', include('subscriptions.urls')),
    path('api/gamification/', include('gamification.urls')),
    path('api/', include('courses.urls')),
    path('api/community/', include('community.urls')),
    path('api/notifications/', include('core.notification_urls')),
    path('api/', include('core.testimonial_urls')),
    path('api/', include('subscriptions.public_urls')),
    path('api/', include('analytics.public_urls')),
    path('api/', include('core.public_urls')),
]

from django.conf import settings
from django.views.static import serve as static_serve
from django.http import HttpResponseForbidden

PROTECTED_MEDIA_PREFIXES = (
    'study_materials/',
    'subjective_exams/',
    'marketplace/materials/',
    'support/attachments/',
)

def secure_media_serve(request, path, document_root=None, show_indexes=False):
    normalized_path = path.replace('\\', '/').lstrip('/')
    for prefix in PROTECTED_MEDIA_PREFIXES:
        if normalized_path.startswith(prefix):
            return HttpResponseForbidden("Direct access to protected media files is forbidden. Please access files via the authorized API.")
    return static_serve(request, path, document_root=document_root, show_indexes=show_indexes)

media_url_prefix = settings.MEDIA_URL.lstrip('/')
urlpatterns += [
    path(f'{media_url_prefix}<path:path>', secure_media_serve, {'document_root': settings.MEDIA_ROOT}),
]
