"""
This module contains views related to user management, including registration, password reset,
and list/customization management. It utilizes Django REST framework and sends
password-reset emails through Brevo's web API.
"""

# Standard imports
import os
import json
import base64
import urllib.error
import urllib.request

# Third-party imports
from rest_framework import mixins, viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.core.validators import validate_email
from urllib.parse import urlencode

# Django imports
from django.shortcuts import get_object_or_404
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.password_validation import validate_password
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

# Local imports
from lista.serializer import (
    ListItemImageSerializer,
    ListItemSerializer,
    GroupListSerializer,
    CustomizationSerializer,
)

from .models import ListItem, GroupList, ListItemImage, Customization
from .serializer import UserSerializer
from .logging_utils import log


# --- Password rules ------------------------------------------------------------------

def password_problem(password, user=None):
    """
    Check a new password against the rules in settings.AUTH_PASSWORD_VALIDATORS
    (at least 8 characters, not a commonly used password, not only digits, not too
    similar to the user's name or email).

    Returns a short, readable explanation of the first problem found (one sentence, so the
    person fixes one thing at a time), or None if the password is fine.

    Used when someone registers or sets a new password through the reset link. Logging in
    is never checked, so people who already have an account are not affected.
    """
    try:
        validate_password(password, user=user)
    except ValidationError as error:
        return error.messages[0]
    return None


# --- Who may edit a list ----------------------------------------------------------
# A list belongs to ListItem.user. It is also shared through GroupList rows, one per
# person, each with a permission_type of "read_only" or "full_access".

def accessible_lists(user):
    """Lists the user owns or that have been shared with them (any permission)."""
    return ListItem.objects.filter(
        models.Q(user=user) | models.Q(shared_with__user=user)
    ).distinct()


def user_can_edit_list(user, list_item):
    """True if the user owns the list or was given full access to it."""
    if list_item.user_id == user.id:
        return True
    return GroupList.objects.filter(
        list_item=list_item, user=user, permission_type='full_access').exists()


@log(user_id="request.user.id", object_id="list_item.id")
@api_view(['GET'])
def get_user_info_by_email(request, email):
    """
    Look up a user by email (used when sharing a list).
    Requires login. Returns only the safe public fields (id, username), never the
    password hash or other account details.
    """
    if not email:
        return Response({"error": "Email parameter is required."}, status=400)

    try:
        user = User.objects.get(email=email)
        serializer = UserSerializer(user)
        return Response(serializer.data)

    except User.DoesNotExist:
        return Response({"error": "User not found."}, status=404)


class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom serializer for obtaining JWT tokens with additional claims.
    This serializer is customized to include additional claims like 
    `username` and `user_id` in the generated JWT token.

    Note:
    - The `create` and `update` methods are not implemented in this class.
    - If you are using this serializer as part of a `ModelSerializer`, 
      you may need to implement the `create` and `update` methods.
    """
    @classmethod
    @log(user_id="request.user.id", object_id="list_item.id")
    def get_token(cls, user):
        """
        Generates a JWT token for the user with additional custom claims.

        This method calls the parent class's `get_token` method to generate
        a basic token, and then adds the `username` and `user_id` claims
        to it. The user's `last_login` is also updated here.

        Args:
            user (User): The user object for whom the token is generated.

        Returns:
            dict: The generated JWT token with added claims.
        """
        token = super().get_token(user)
        token['username'] = user.username
        token['user_id'] = user.id
        user.last_login = timezone.now()
        user.save()
        return token


class MyTokenObtainPairView(TokenObtainPairView):
    """
    Custom view for obtaining JWT tokens.
    """
    serializer_class = MyTokenObtainPairSerializer


@log(user_id="request.user.id", object_id="list_item.id")
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Register a new user with username, email, and password.

    This endpoint allows the creation of a new user by providing a username, email, password, 
    first name, and last name. The server checks whether the username or email already exists 
    in the database, and if so, returns an error. The password must also meet the password
    rules (see password_problem); otherwise a 400 explains what to change. If the
    registration is successful, a new user is created, and access and refresh tokens are
    returned for further use.
    """
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    if not username or not email or not password:
        return Response({'error': 'Username, email and password are required.'},
                        status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({'error': 'Username already exists.'},
                        status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response({'error': 'Email already in use.'},
                        status=status.HTTP_400_BAD_REQUEST)

    # Check the password against the rules, using an unsaved User so the "too similar to
    # the username/email" rule has something to compare with.
    problem = password_problem(password, User(
        username=username, email=email,
        first_name=request.data.get('first_name', ''),
        last_name=request.data.get('last_name', '')))
    if problem:
        return Response({'error': problem}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=request.data.get('first_name', ''),
        last_name=request.data.get('last_name', '')
    )
    # New accounts are normal users: no is_staff flag, so no access to the admin site.
    user.is_active = True
    user.last_login = timezone.now()
    user.save()
    refresh = MyTokenObtainPairSerializer.get_token(user)
    access = str(refresh.access_token)

    return Response({
        'Success': 'New user created',
        'username': user.username,
        'user_id': user.id,
        'access': access,
        'refresh': str(refresh),
    }, status=status.HTTP_201_CREATED)


@log(user_id="request.user.id", object_id="list_item.id")
@api_view(['GET', 'PATCH'])
def update_user(request, user_id):
    """
    Update user profile information.

    This view handles two types of requests:
    1. GET: Fetches the current profile data (username, first name, last name, email).
    2. PATCH: Updates the user's profile with the provided data.

    When updating, the function performs several checks:
    - Ensures that the provided email is valid and unique.
    - Ensures that the provided username is unique.
    - Ensures that the request is being made by the user themselves 
    (no one else can update the profile of another user).

    If any of the required fields (email, username) already exist in the system,
    a 400 error will be returned.
    If the request is successful, a 200 status with a success message is returned.
    A profile is private: the request needs a login token (401 otherwise) and the token
    must belong to that same user (403 otherwise).
    """
    if request.user.id != user_id:
        return Response({'error': 'You can only access your own profile.'},
                        status=status.HTTP_403_FORBIDDEN)

    user = get_object_or_404(User, pk=user_id)

    if request.method == 'GET':
        user_data = {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email
        }
        return Response(user_data, status=status.HTTP_200_OK)

    if request.method == 'PATCH':
        data = request.data

        if 'username' in data:
            username = data['username']
            if User.objects.filter(username=username).exclude(id=user.id).exists():
                return Response({'error': 'Username already exists.'},
                                status=status.HTTP_400_BAD_REQUEST)

        if 'email' in data:
            email = data['email']
            try:
                validate_email(email)
            except ValidationError:
                return Response(
                    {"error": "Invalid email format."}, status=status.HTTP_400_BAD_REQUEST)

            if User.objects.filter(email=email).exclude(id=user.id).exists():
                return Response({'error': 'Email already in use.'},
                                status=status.HTTP_400_BAD_REQUEST)

        user.username = data.get('username', user.username)
        user.first_name = data.get('first_name', user.first_name)
        user.last_name = data.get('last_name', user.last_name)
        user.email = data.get('email', user.email)
        user.save()

        return Response({"message": "Profile updated successfully!"}, status=status.HTTP_200_OK)

    return Response({"error": "Invalid request method."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class ResetPasswordView(APIView):
    """
    View for resetting the user's password.

    Public (the user is logged out), but it only works with the token from the password-
    reset email. The token is single-use (changing the password invalidates it) and expires
    after PASSWORD_RESET_TIMEOUT (see settings.py). The new password must meet the password
    rules (see password_problem).
    """
    permission_classes = [AllowAny]

    @log(user_id="request.user.id", object_id="list_item.id")
    def post(self, request):
        """
        Resets the user's password using the provided email and new password.
        """
        email = request.data.get("email")
        new_password = request.data.get("password")
        token = request.data.get("token")

        if not email or not new_password:
            return Response(
                {"error": "Email and new password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not token:
            return Response(
                {"error": "This reset link is incomplete. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": "User with this email does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # The token is tied to this user, their current password and their last login,
        # so it stops working once it has been used or after PASSWORD_RESET_TIMEOUT.
        if not default_token_generator.check_token(user, token):
            return Response(
                {"error": "This reset link is invalid or has expired. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Checked after the token on purpose: a weak password is refused without using up
        # the link, so the person can simply try again with a stronger one.
        problem = password_problem(new_password, user)
        if problem:
            return Response({"error": problem}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()

        return Response(
            {"message": "Password reset successfully."},
            status=status.HTTP_200_OK,
        )


BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


@log(user_id="request.user.id", object_id="list_item.id")
def send_password_reset_email(user):
    """
    Sends a password reset email to the user through Brevo's web API. Returns True if
    Brevo accepted the email, False if it could not be sent.

    The link carries a single-use, expiring token (see ResetPasswordView). The email
    address is URL-encoded so characters such as "+" survive the trip. The API key is only
    ever sent to Brevo and is never written to the log.
    """
    if not settings.BREVO_API_KEY:
        print("Error sending email: BREVO_API_KEY is not set")
        return False

    token = default_token_generator.make_token(user)
    query = urlencode({"email": user.email, "token": token})

    message = (
        "Click the link to reset your password: "
        f"{settings.FRONTEND_URL}/change-password?{query}\n\n"
        "The link works once and expires in one hour. "
        "If you did not ask for it, you can ignore this email."
    )

    payload = {
        "sender": {"name": settings.EMAIL_SENDER_NAME, "email": settings.DEFAULT_FROM_EMAIL},
        "to": [{"email": user.email}],
        "subject": "Password Reset Request",
        "textContent": message,
    }
    api_request = urllib.request.Request(
        BREVO_SEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": settings.BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(api_request, timeout=15) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as e:  # Brevo answered with an error (bad key, sender...)
        print(f"Error sending email: Brevo answered {e.code}: {e.read()[:300]!r}")
        return False
    except Exception as e:  # connection blocked, timeout...
        print(f"Error sending email: {str(e)}")
        return False


class ResetPasswordRequestView(APIView):
    """
    View for handling password reset requests.

    This view processes a password reset request by verifying the user's email 
    and sending a reset email containing a link if the user exists in the database.
    Public by design: the user is not logged in when they forget their password.
    """
    permission_classes = [AllowAny]

    @log(user_id="request.user.id", object_id="None")
    def post(self, request):
        """
        Handles the POST request for initiating a password reset.
        Takes an email and sends a reset email if the user exists.
        """
        email = request.data.get("email")
        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)

            # If Brevo did not accept the email (wrong key, unverified sender, blocked
            # connection...) tell the user instead of pretending it was sent.
            if not send_password_reset_email(user):
                return Response(
                    {"error": "We couldn't send the email right now. Please try again later."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            return Response(
                {"message": "Password reset email has been sent."},
                status=status.HTTP_200_OK,
            )

        except User.DoesNotExist:
            return Response(
                {"error": "User with this email does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class ListItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing ListItems, including CRUD operations
    and functionality for soft deletion of items.

    Requires login. A user only sees lists they own or that were shared with them, and
    only owners and people with full access may change a list.

    Deleting a list from the app is a soft delete: the app sends PATCH {"is_active": false}
    and the row stays in the database, so nothing is lost permanently.
    """
    queryset = ListItem.objects.all()
    serializer_class = ListItemSerializer

    @log(user_id="request.user.id", object_id="list_item.id")
    def get_queryset(self):
        """
        Lists the user owns or that are shared with them, optionally filtered by user_id.
        """
        queryset = accessible_lists(self.request.user)
        user_id = self.request.query_params.get('user_id')
        return queryset.filter(user_id=user_id) if user_id else queryset

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=False, methods=['GET'], url_path=r'by-user/(?P<user_id>\d+)')
    def get_by_user(self, request, user_id=None):
        """
        Retrieves the list items for a specific user.
        """
        user = request.user
        if user.is_anonymous:
            raise PermissionDenied("User not logged in.")
        user_items = ListItem.objects.filter(user=user)
        serializer = ListItemSerializer(user_items, many=True)
        return Response(serializer.data)

    @log(user_id="request.user.id", object_id="list_item.id")
    def perform_update(self, serializer):
        """
        Perform update of list item, ensuring the user is authenticated.
        """
        user = self.request.user
        if user.is_anonymous:
            raise PermissionDenied("User not logged in.")
        if not user_can_edit_list(user, serializer.instance):
            raise PermissionDenied("You do not have permission to edit this list.")
        serializer.save(user=user)

    @log(user_id="request.user.id", object_id="list_item.id")
    def perform_destroy(self, instance):
        """
        Hard delete (not used by the app, which hides lists with PATCH is_active=false).
        Only people who may edit the list can do it.
        """
        if not user_can_edit_list(self.request.user, instance):
            raise PermissionDenied("You do not have permission to delete this list.")
        instance.delete()

    @log(user_id="request.user.id", object_id="list_item.id")
    def perform_create(self, serializer):
        """
        Perform creation of a list item, ensuring the user is authenticated.
        """
        user = self.request.user
        if user.is_anonymous:
            raise PermissionDenied("User not logged in.")
        serializer.save(user=user)

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=True, methods=['patch'])
    def delete_item(self, request, pk=None):
        """
        Soft delete the list item by setting `is_active` to False.
        """
        user = request.user
        if user.is_anonymous:
            raise PermissionDenied("User not logged in.")
        try:
            list_item = self.get_object()
            list_item.is_active = False
            list_item.save()
            return Response(
                {"message": "Item successfully deleted!"}, status=200)

        except ListItem.DoesNotExist:
            return Response({"error": "Item not found!"}, status=404)


class GroupListViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    ViewSet for GroupLists, the rows that say who can open a list and with which permission.

    Deliberately limited to what the app uses: creating a row (sharing a list) and the two
    read actions below (`by-user` for Home, `permission_type` for the edit screen). The
    generic list / retrieve / update / delete endpoints are not exposed, so nobody can
    browse, change or remove other people's shares through them.
    """
    queryset = GroupList.objects.all()
    serializer_class = GroupListSerializer
    permission_classes = [IsAuthenticated]

    @log(user_id="request.user.id", object_id="list_item.id")
    def create(self, request, *args, **kwargs):
        """
        Creates a new GroupList and associates it with the currently logged-in user.
        The function accepts data from the request, validates it, and creates a new GroupList.

        Returns:
            Response: A message with the details of the created GroupList or an error 
            if creation fails.
        """
        # Only the list's owner, or someone with full access to it, may add people to it.
        try:
            list_item = ListItem.objects.filter(id=request.data.get('list_item')).first()
        except (TypeError, ValueError):
            list_item = None  # not a valid id: let the serializer report the 400
        if list_item is not None and not user_can_edit_list(request.user, list_item):
            return Response(
                {'message': 'You are not allowed to share this list.'},
                status=status.HTTP_403_FORBIDDEN
            )

        data = request.data.copy()
        data['user'] = request.data.get('user')

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {'message': 'GroupList created successfully', 'data': serializer.data},
            status=status.HTTP_201_CREATED
        )

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=False, methods=['GET'], url_path=r'by-user/(?P<user_id>\d+)')
    def list_by_user(self, request, user_id):
        """
        Returns the ListItems associated with a specific user based on the user_id.

        The function fetches GroupLists where the logged-in user is associated and retrieves 
        the ListItems related to those GroupLists.

        Args:
            user_id (str): The ID of the user whose ListItems are to be fetched.

        Returns:
            Response: A list of serialized ListItems associated with the user.
        """
        user_id = request.user.id
        group_list = GroupList.objects.filter(models.Q(user_id=user_id))
        list_item_ids = group_list.values_list('list_item_id', flat=True)
        items = ListItem.objects.filter(id__in=list_item_ids)
        serializer = ListItemSerializer(items, many=True)
        return Response(serializer.data)

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=False, methods=['GET'], url_path='permission_type')
    def get_permission_type(self, request):
        """
        Fetches the permission type for a specific user and ListItem based on 
        the provided user_id and list_item_id.

        The function checks if both user_id and list_item_id are provided. If either is missing,
        it returns an error message. If valid, it returns the permission type 
        for the specified user and ListItem.

        Args:
            user_id (str): The ID of the user whose permission type is being checked.
            list_item_id (str): The ID of the ListItem for which the permission type
            is being checked.

        Returns:
            Response: The permission type for the specified user and ListItem or an error message 
            if parameters are missing or the group list is not found.
        """
        user_id = request.query_params.get('user_id')
        list_item_id = request.query_params.get('list_item_id')

        if not user_id or not list_item_id:
            return Response({'message': 'user_id and list_item_id are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        print(f"Fetching permission for user_id: {user_id} "
              f"and list_item_id: {list_item_id}")

        group_list = GroupList.objects.filter(
            user_id=user_id, list_item_id=list_item_id).first()

        if not group_list:
            return Response(
                {'message': 'No group list found for the given user and item'},
                status=status.HTTP_404_NOT_FOUND
            )

        print(f"Permission type found: {group_list.permission_type}")

        return Response({'permission_type': group_list.permission_type}, status=status.HTTP_200_OK)

class ListItemImageViewSet(viewsets.ModelViewSet):
    """
    A viewset for handling image uploads, retrieval, and updates for list items.

    This viewset provides three key actions:
    1. `upload_images`: Allows the user to upload multiple images for a specific list item.
    2. `get_images_for_list_item`: Retrieves all images associated with a given list item.
    3. `update_images`: Allows the user to update or delete images for a list item,
    including modifying their index.

    Each action handles different HTTP methods (POST, GET) and validates inputs to ensure
    correct handling of list item images.
    """

    queryset = ListItemImage.objects.all()
    serializer_class = ListItemImageSerializer

    def get_permissions(self):
        """
        Reading a list's images is public (the app's image request carries no token, and
        the image files themselves are public URLs). Everything else needs a login.
        """
        if self.action == 'get_images_for_list_item':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        """Only images that belong to lists the user can access."""
        return ListItemImage.objects.filter(list_item__in=accessible_lists(self.request.user))

    def _require_edit_rights(self, list_item):
        if not user_can_edit_list(self.request.user, list_item):
            raise PermissionDenied("You do not have permission to edit this list.")

    def perform_create(self, serializer):
        self._require_edit_rights(serializer.validated_data['list_item'])
        serializer.save()

    def perform_update(self, serializer):
        self._require_edit_rights(serializer.instance.list_item)
        self._require_edit_rights(serializer.validated_data.get('list_item', serializer.instance.list_item))
        serializer.save()

    def perform_destroy(self, instance):
        self._require_edit_rights(instance.list_item)
        instance.delete()

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=False, methods=['post'], url_path='upload_images')
    def upload_images(self, request):
        """
        Handle POST request to upload images for a given list item.

        This endpoint allows the user to upload multiple images for a specific 
        list item by providing the list item ID and an array of base64 encoded 
        image data. Each image is saved to the file system, and the corresponding 
        `ListItemImage` instances are created in the database.

        Request data:
        - list_item (required): The ID of the list item to associate images with.
        - images (required): A list of base64 encoded image data containing 
          'uri', 'fileName', 'mimeType', and 'index'.

        Returns:
        - HTTP 201 Created with a success message if the upload is successful.
        - HTTP 400 Bad Request if the list_item or images array is missing, 
          or if the base64 decoding fails.
        """
        list_item_id = request.data.get('list_item')
        images_data = request.data.getlist('images')

        if not list_item_id:
            return Response({"error": "list_item is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not images_data:
            return Response({"error": "images array is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            list_item = ListItem.objects.get(id=list_item_id)
        except ListItem.DoesNotExist:
            return Response({"error": "List item not found."}, status=status.HTTP_404_NOT_FOUND)

        if not user_can_edit_list(request.user, list_item):
            return Response({"error": "You do not have permission to edit this list."},
                            status=status.HTTP_403_FORBIDDEN)

        image_instances = []
        for image_data in images_data:
            try:
                image_json = json.loads(image_data)
                base64_image = image_json['uri']
                file_name = image_json['fileName']
                mime_type = image_json['mimeType']
                image_index = image_json['index']

                extension = mime_type.split(
                    '/')[1] if '/' in mime_type else 'jpeg'
                image_file_name = (
                    f"{file_name or f'image_{image_index}'}."
                    f"{extension}"
                )

                image_data = base64.b64decode(base64_image)
                image_content = ContentFile(image_data, name=image_file_name)
                file_path = default_storage.save(os.path.join('list_item_images', image_file_name),
                                                 image_content)

                image_instance = ListItemImage(
                    list_item=list_item,
                    image=file_path,
                    index=image_index,
                    mime_type=mime_type
                )
                image_instances.append(image_instance)
            except Exception as e:
                return Response({"error": "Failed to decode base64 image", "details": str(e)},
                                status=status.HTTP_400_BAD_REQUEST)

        ListItemImage.objects.bulk_create(image_instances)
        return Response({"status": "Images uploaded successfully"}, status=status.HTTP_201_CREATED)

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=True, methods=['GET'], url_path='get_images_for_list_item')
    def get_images_for_list_item(self, request, *args, **kwargs):
        """
        Handle GET request to retrieve all images associated with a 
        given list item.

        This endpoint retrieves all images related to a specific list item by 
        its ID. The images are returned in a JSON response containing the 
        image URL, index, and image ID.

        Request parameters:
        - pk (required): The ID of the list item.

        Returns:
        - HTTP 200 OK with a list of images if found.
        - HTTP 200 OK with an empty list and a message if no images are found.
        """
        list_item_id = kwargs.get('pk')

        images = ListItemImage.objects.filter(list_item_id=list_item_id)
        if not images.exists():
            return Response(
                {"images": [], "message": "No images found for this list item."}, status=200)

        image_data = [
            {
                "id": image.id,
                "url": image.image.url,
                "index": image.index
            } for image in images
        ]
        return Response({"images": image_data})

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=False, methods=['post'], url_path='update_images')
    def update_images(self, request, *args, **kwargs):
        """
        Handle POST request to update or delete images for a given list item.

        This endpoint allows the user to update the indexes of existing images 
        and delete images by their index. The `list_item_id` must be provided 
        along with the indices of images to update or delete.

        Request data:
        - list_item_id (required): The ID of the list item.
        - updatedImagesIndex[] (optional): A list of indices of images to 
          update.
        - deletedImagesIndex[] (optional): A list of indices of images to 
          delete.

        Returns:
        - HTTP 200 OK with a success message if the images are updated and/or 
          deleted successfully.
        - HTTP 400 Bad Request if any errors occur during the update or 
          deletion process.
        """
        list_item_id = request.data.get('list_item_id')
        list_item = ListItem.objects.filter(id=list_item_id).first()
        if list_item is not None and not user_can_edit_list(request.user, list_item):
            return Response({"error": "You do not have permission to edit this list."},
                            status=status.HTTP_403_FORBIDDEN)

        # NOTE: images marked as deleted are currently only logged below, not removed;
        # only the index shift for "updated" images is applied. Kept as-is on purpose.
        updated_images_index = request.data.getlist('updatedImagesIndex[]')
        deleted_images_index = request.data.getlist('deletedImagesIndex[]')
        try:

            for deleted_index in deleted_images_index:
                images_to_delete = ListItemImage.objects.filter(
                    index=deleted_index, list_item_id=list_item_id)
                print(f"Found images to delete with index"
                      f"{deleted_index}:{images_to_delete}")
                for image in images_to_delete:
                    print(
                        f"Deleting image {image.id}"
                        f"with index {image.index}) image.delete()")

            for updated_index in updated_images_index:
                images_to_update = ListItemImage.objects.filter(
                    index=updated_index, list_item_id=list_item_id)
                print(
                    f"Found images with index"
                    f"{updated_index}:{images_to_update}")
                for image in images_to_update:
                    print(
                        f"Updating image {image.id} - Old index: {image.index}"
                    )
                    image.index -= 1

                    try:
                        image.save()
                        print(
                            f"Image {image.id} saved successfully with new index {image.index}")
                    except Exception as e:
                        print(f"Failed to save image {image.id}: {e}")

            return Response(
                {"message": "Images updated and deleted successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"Error during update: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CustomizationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for handling user background customizations. Allows users to create, update,
    and retrieve their customization settings (e.g., background image).
    """
    queryset = Customization.objects.all()
    serializer_class = CustomizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """A user only ever sees their own customization."""
        return Customization.objects.filter(user=self.request.user)

    @log(user_id="request.user.id", object_id="list_item.id")
    def create(self, request, *args, **kwargs):
        """
        Handle POST request to create or update a user's background customization.

        This method is responsible for:
        - Checking if the required 'background_image_id' is provided.
        - Creating or updating the Customization model instance for the authenticated user.
        - Responding with a success message and the updated data.

        If 'background_image_id' is missing, a 400 error is returned.

        Args:
            request: The HTTP request object containing user data.

        Returns:
            Response: HTTP response with a success or error message.
        """
        user = request.user
        background_image_id = request.data.get('background_image_id', '')

        if not background_image_id:
            return Response(
                {"error": "background_image_id is required."},
                status=400
            )

        customization, created = Customization.objects.update_or_create(
            user=user,
            defaults={'background_image_id': background_image_id}
        )

        serializer = CustomizationSerializer(customization)
        return Response(
            {
                "message": "Background updated successfully.",
                "data": serializer.data,
                "status": "created" if created else "updated"
            },
            status=201 if created else 200
        )

    @log(user_id="request.user.id", object_id="list_item.id")
    @action(detail=False, methods=['GET'], url_path='get_user_customization')
    def get_customization_for_user(self, request, *args, **kwargs):
        """
        Handle GET request to retrieve the customization for the authenticated user.

        This method retrieves the background customization for the authenticated user.
        If the customization does not exist, a message indicating the absence of customization
        is returned with a 200 status.

        Args:
            request: The HTTP request object containing user data.

        Returns:
            Response: HTTP response with the user's customization data or a not found message.
        """
        user = request.user

        try:
            customization = Customization.objects.get(user=user)
        except Customization.DoesNotExist:
            return Response({
                "message": "Customization not found for this user.",
                "data": {}
            }, status=200)

        serializer = CustomizationSerializer(customization)
        return Response({
            "message": "Customization retrieved successfully.",
            "data": serializer.data
        }, status=200)
