[← Back to the README](../Readme.md)

# Data Model

### **Users**  
Utilizes Django’s built-in `User` model:  
- **User ID**: Unique identifier.  
- **Username**: Unique within the system, used for login alongside the password
- **First and last name**: optional. The app no longer asks for them, so new accounts have them empty; they are kept for existing accounts and for older app versions that still send them.  
- **Email**: Unique within the system, used for sharing lists and password recovery.  
- **Password**: Secure authentication credential (stored hashed; must meet the strength rules).  

### **ListItem**  
Represents tasks or list items:  
- **List ID**: Unique identifier for the list.  
- **Title**: Default: `"No items"`.  
- **Items**: Stored as plain text, separated by `|`. A checked item starts with `✔️ `.  
- **Creation Date**: Auto-generated upon list creation.  
- **Owner**: Associated with the user who created it (`user`).  
- **Status**: Active or inactive (`is_active`). Deleting a list in the app sets it to inactive.  
- **Picture rows** (`picture_rows`): not stored; calculated for every response. It lists the row positions (the first row is `0`) that have a picture.  

### **GroupList**  
Manages collaborative list sharing:  
- **User**: Reference to a participating user.  
- **List**: Reference to the shared list.  
- **Join Date**: Date user joined the group.  
- **Role**: Either `Admin` or `Member`.  
- **Permissions**: `Read-Only` or `Full Access`.  

### **ListItemImage**  
Stores images associated with a specific list item and index:
- **List Item**: A foreign key linking to the ListItem model (on_delete=models.CASCADE, related_name='images').
- **Image**: An image file, optional (default='/placeholder.png', upload_to='list_item_images/').
- **Index**: The row the picture belongs to (the first row is `0`), defaults to 0. A row can have only one picture.
- **MIME Type**: Optional field to store the image's MIME type (max_length=50).

### **Customization**  
Allows users to personalize their experience:  
- **User**: Reference to the modifying user.  
- **Background**: Identifier for a custom background image.  

When a picture record is deleted (picture removed or replaced, or a list deleted for good), its file on disk is deleted too, once the change has been saved.

> There is no table for AI suggestions: they are generated on request by the frontend's Netlify function and are not stored.
