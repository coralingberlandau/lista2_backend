########### application ############

"""
This file contains the URL routing configuration for the Django application.
It registers view sets with a router and maps various API endpoints to their corresponding views.

Key Features:
- A DefaultRouter is used to automatically generate URLs for the viewsets.
- Several API endpoints are registered for models like ListItem, GroupList, ListItemImage,
  and Customization.
- Each URL path is associated with a specific view or viewset that handles the respective request.

Registered Endpoints:
1. /login/ - Endpoint for token-based authentication login (returns access + refresh tokens).
2. /token/refresh/ - Exchange a refresh token for a new access token.
3. /register/ - User registration endpoint.
4. /get_user_info/<email>/ - Look up a user's id by email (used when sharing a list).
5. /user/<user_id>/ - Read or update your own profile (login required).
6. /reset_password_request/ - Request a password reset.
7. /reset_password/ - Set a new password (needs the token from the reset email).

The URLs are dynamically generated using the DefaultRouter for
models that follow the RESTful pattern.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views
from .views import (CustomizationViewSet, GroupListViewSet,
                    ListItemImageViewSet, ListItemViewSet)

router = DefaultRouter()
router.register(r'listitem', ListItemViewSet, basename='listitem')
router.register(r'grouplists', GroupListViewSet)
router.register(r'listitemimages', ListItemImageViewSet)
router.register(r'customizations', CustomizationViewSet)

urlpatterns = [
    path('login/', views.MyTokenObtainPairView.as_view()),
    # Exchange a refresh token for a new access token (and a rotated refresh token).
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', views.register),
    path('', include(router.urls)),
    path('get_user_info/<str:email>/', views.get_user_info_by_email,
         name='get_user_info_by_email'),
    path('user/<int:user_id>/', views.update_user, name='update_user'),
    path('reset_password_request/', views.ResetPasswordRequestView.as_view(),
         name='reset_password_request'),
    path('reset_password/', views.ResetPasswordView.as_view(), name='reset_password'),
]
