"""
This file contains the serializers for various models in the Django application, facilitating 
the conversion of model instances into JSON format for easy API interaction.

Models Handled:
1. User: Serializes only the safe public fields (id, username) of the built-in User model.
2. ListItem: Serializes a model representing individual items in a list, including attributes such
   as user (the owner of the item) and images (optional associated images).
3. GroupList: Serializes a model that represents a group of users who can share a ListItem,
   including additional logic to fetch the ID of the user who shared the list.
4. ListItemImage: Serializes a model that stores images associated with ListItem objects.
5. Customization: Serializes a model representing user-specific customizations or preferences.

Key Features:
- Each serializer maps model fields to their respective JSON representations.
- Custom validation logic is implemented for ensuring required fields, particularly in the 
  GroupListSerializer, where the presence of a user is checked.
- The GroupListSerializer includes a custom method (get_shared_by_user_id) to retrieve the user who 
  shared a particular list.
- The extra_kwargs attribute is used in the ListItemSerializer to define custom requirements for 
  fields, like making the user field required and images optional.

Purpose:
The serializers are part of the API infrastructure and ensure that the application’s models can 
easily be serialized into a format that can be sent or received over HTTP, making the app's data 
accessible for web or mobile interfaces.
"""

from django.contrib.auth.models import User
from rest_framework import serializers
from .models import (Customization, GroupList, ListItem, ListItemImage)


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the User model, used to convert User instances into JSON format.
    It serializes only the safe public fields. It must never expose the password hash
    or account flags, because it is used by the share-by-email lookup.
    """
    class Meta:
        """
        Meta class specifying model and fields for the serializer.
        """
        model = User
        fields = ['id', 'username']


class ListItemSerializer(serializers.ModelSerializer):
    """
    Serializer for the ListItem model, used to convert ListItem instances into JSON format.
    It serializes all fields of the ListItem model, with specific extra_kwargs settings to
    define custom requirements for the user and images fields.

    Fields:
    - user: The user who owns the list item (required).
    - images: Associated images for the list item (optional).
    - items: The list content. May be empty, so a list can be created with a title first
      and filled in later (the title is still required).

    extra_kwargs:
    - user: The user field is required.
    - images: The images field is optional.
    - items: An empty value is allowed.
    """
    class Meta:
        """
        Meta class specifying model and fields for the serializer.
        """
        model = ListItem
        fields = '__all__'
        extra_kwargs = {
            'user': {'required': True},
            'images': {'required': False},
            'items': {'allow_blank': True},
        }


class GroupListSerializer(serializers.ModelSerializer):
    """
    Serializer for the GroupList model, used to convert GroupList instances into JSON format.
    This serializer includes logic for retrieving the ID of the user who shared a particular list.
    
    Fields:
    - user: The user associated with the group list.
    - list_item: The list item that is shared in the group.
    - shared_by_user_id: The ID of the user who shared the list item (calculated dynamically).

    Methods:
    - get_shared_by_user_id: Retrieves the ID of the user who shared the list item.
    - validate: Ensures that the 'user' field is included in the request.
    """
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    list_item = serializers.PrimaryKeyRelatedField(queryset=ListItem.objects.all())
    shared_by_user_id = serializers.SerializerMethodField()

    class Meta:
        """
        Meta class specifying model and fields for the serializer.
        """
        model = GroupList
        fields = '__all__'

    def get_shared_by_user_id(self, obj):
        """
        Retrieves the user ID of the user who shared the list item.
        If the list item is shared with the user, the user's ID is returned.
        Otherwise, None is returned.

        Parameters:
        - obj: The GroupList instance for which to fetch the shared_by_user_id.

        Returns:
        - The user ID of the user who shared the list, or None if not shared.
        """
        shared_with = obj.list_item.shared_with.filter(user=obj.user).first()
        if shared_with:
            return shared_with.user.id
        return None

    def validate(self, attrs):
        """
        Custom validation to ensure that the 'user' field is included in the request.
        If the 'user' field is missing, a validation error is raised.

        Parameters:
        - attrs: The fields provided in the request to validate.

        Returns:
        - attrs: The validated fields if the 'user' field is present.

        Raises:
        - ValidationError: If the 'user' field is missing.
        """
        if 'user' not in attrs:
            raise serializers.ValidationError(
                {"user": "This field is required."})
        return attrs


class ListItemImageSerializer(serializers.ModelSerializer):
    """
    Serializer for the ListItemImage model, used to convert ListItemImage instances into
    JSON format.This serializer handles images associated with ListItem objects.

    Fields:
    - image: The image associated with a ListItem object.
    - list_item: The related ListItem object.
    """
    class Meta:
        """
        Meta class specifying model and fields for the serializer.
        """
        model = ListItemImage
        fields = '__all__'


class CustomizationSerializer(serializers.ModelSerializer):
    """
    Serializer for the Customization model, used to convert Customization instances into
    JSON format. This serializer handles user-specific customizations or preferences.

    Fields:
    - user: The user associated with the customization.
    - preferences: The preferences or settings for the user.
    """
    class Meta:
        """
        Meta class specifying model and fields for the serializer.
        """
        model = Customization
        fields = '__all__'
