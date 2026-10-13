"""
This module contains Django models for managing lists, group memberships, images,
and customizations.

Models:

1. ListItem: Represents a list of items owned by a user. It includes attributes such
   as title, list content, creation date, and user ownership.
2. GroupList: Represents a group that has access to a ListItem. It stores the user's
   role (member/admin), permission type (read-only/full access), and the date the
   user joined the group.
3. ListItemImage: Represents an image associated with a ListItem, including image
   file, index, and mime type.
4. Customization: Represents user-specific customization settings, including the
   background image ID.

Each model leverages Django's built-in features like ForeignKey relationships, model
fields, and auto-generated timestamps.
"""


import logging

from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)

class ListItem(models.Model):
    """
    Represents a list item that belongs to a user. Each ListItem can store a title,
    a list of items, a creation date, and a user who owns the list. It also tracks
    whether the list item is active or not.
    
    Attributes:
        title (str): A string representing the title of the ListItem. Defaults to 'No items'.
        items (str): A string that holds the list content. Defaults to 'No items'.
        date_created (date): The date when the ListItem was created, auto-populated upon creation.
        user (ForeignKey): A reference to the User who owns this list item.
        is_active (bool): A flag that indicates whether the ListItem is active or not.
        Defaults to True.
    """
    title = models.CharField(max_length=255, default="No items")
    items = models.TextField(default="No items")
    date_created = models.DateField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_lists')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        """
        Returns a string representation of the ListItem, displaying the title.

        Returns:
            str: The title of the ListItem.
        """
        return str(self.title)

class GroupList(models.Model):
    """
    Represents a group that has access to a specific ListItem.
    Each user in the group is assigned a role (member or admin) 
    and has a specific permission type (read-only or full access).
    
    Attributes:
        ROLE_CHOICES (list of tuples): A list of possible roles that a user can have in the group
            (member or admin).
        PERMISSION_CHOICES (list of tuples): A list of possible permissions a user can have in the
            group (read-only or full access).
        user (ForeignKey): A reference to the User who belongs to the group.
        list_item (ForeignKey): A reference to the ListItem that the group has access to.
        date_joined (date): The date when the user joined the group, auto-populated.
        role (str): The role of the user in the group (member or admin).
        permission_type (str): The permission level granted to the user (read-only or full access).
    """
    ROLE_CHOICES = [
        ('member', 'Member'),
        ('admin', 'Admin'),
    ]

    PERMISSION_CHOICES = [
        ('read_only', 'Read-Only'),
        ('full_access', 'Full Access'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_lists")
    list_item = models.ForeignKey(ListItem, on_delete=models.CASCADE, related_name="shared_with")
    date_joined = models.DateField(auto_now_add=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')
    permission_type = models.CharField(
    max_length=20,choices=PERMISSION_CHOICES, default='read_only')

    def __str__(self):
        """
        Returns a string representation of the GroupList showing the user ID, list item ID,
        their role, and permission type.
        
        Returns:
            str: A formatted string showing user ID, list item ID, role, and permission type.
        """
        user_id = self.user.pk if self.user else None
        list_item_id = self.list_item.pk if self.list_item else None
        role = self.role
        permission_type = self.permission_type

        return (
            f"User ID: {user_id} - "
            f"List Item ID: {list_item_id} - "
            f"{role} - {permission_type}"
        )


class ListItemImage(models.Model):
    """
    Represents an image associated with a specific ListItem. The image is stored along
    with metadata such as the image index and MIME type.
    
    Attributes:
        list_item (ForeignKey): A reference to the ListItem the image is associated with.
        image (ImageField): The actual image file uploaded for the ListItem.
        index (int): The index or order of the image within the ListItem.
        mime_type (str): The MIME type of the image, if available.
    """
    list_item = models.ForeignKey(
        ListItem, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(
        null=True, blank=True, default='/placeholder.png', upload_to='list_item_images/')
    index = models.PositiveIntegerField(default=0)
    mime_type = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        """
        Returns a string representation of the ListItemImage, displaying the associated ListItem ID
        and the image file name.

        Returns:
            str: A formatted string showing ListItem ID and image name.
        """
        return f"Image for ListItem PK: {self.list_item.pk} - {self.image.name}"

@receiver(post_delete, sender=ListItemImage)
def remove_picture_file(sender, instance, **kwargs):
    """
    Deletes a picture's file from disk when its record is deleted (one picture, a whole
    list deleted for good, or a picture replaced). The file is removed only after the
    change has been saved: if the change is rolled back, the file stays.
    """
    name = instance.image.name if instance.image else ''
    if not name or name.startswith('/'):
        return  # empty, or the default placeholder: there is no stored file to remove
    storage = instance.image.storage

    def delete_file():
        try:
            storage.delete(name)
        except Exception:  # a missing or locked file must never break the request
            logger.exception("Could not delete picture file %s", name)

    transaction.on_commit(delete_file)


class Customization(models.Model):
    """
    Represents user-specific customizations, particularly the background image associated
    with the user's profile or preferences.

    Attributes:
        user (ForeignKey): A reference to the User who owns this customization.
        background_image_id (str): The ID of the background image used by the user.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    background_image_id = models.CharField(max_length=20, default='')

    def __str__(self):
        """
        Returns a string representation of the Customization, showing the user ID and the background
        image ID associated with the customization.

        Returns:
            str: A formatted string showing user ID and background image ID.
        """
        user_identifier = self.user.id
        background_image = self.background_image_id

        return (f"Customization for user {user_identifier} - "
                f"image ID: {background_image}")
