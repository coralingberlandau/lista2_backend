[← Back to the README](../Readme.md)

# API Reference

All paths are relative to the backend address. Unless marked **public**, send `Authorization: Bearer <access token>`.

### User Authentication  
#### Register  (public)
- **URL:** `/register/`  
- **Method:** `POST`  
- **Body Example:**  
  ```json
  {
    "username": "user1",
    "email": "user1@example.com",
    "password": "a-strong-password-42"
  }
  ```
- **Response (201):**
  ```json
  { "Success": "New user created", "username": "user1", "user_id": 1, "access": "...", "refresh": "..." }
  ```
- **Optional fields:** `first_name` and `last_name` are accepted but not required (older app versions still send them). Only `username`, `email` and `password` are required.  
- **Errors (400):** missing fields, `Username already exists.`, `Email already in use.`, or the first password-rule problem 
  (for example `This password is too short. It must contain at least 8 characters.`).

#### Login  (public)
- **URL:** `/login/`  
- **Method:** `POST`  
- **Body Example:**  
  ```json
  {
    "username": "user1",
    "password": "a-strong-password-42"
  }
  ```
- **Response (200):** `{ "access": "...", "refresh": "..." }`  
- **Error (401):** wrong username or password.

#### Renew the session  (public)
- **URL:** `/token/refresh/`  
- **Method:** `POST`  
- **Body:** `{ "refresh": "..." }`  
- **Response (200):** `{ "access": "...", "refresh": "..." }` (the old refresh token is blacklisted)  
- **Error (401):** the refresh token is invalid, used or expired.

#### Look up a user by email (used for sharing)
- **URL:** `/get_user_info/{email}/`  
- **Method:** `GET`  
- **Response (200):** `{ "id": 5, "username": "dan" }`  
- **Error (404):** `{ "error": "User not found." }`

#### Profile (own only)
- **URL:** `/user/{user_id}/`  
- **Methods:** `GET`, `PATCH`  
- **GET response:** `{ "username": "...", "first_name": "...", "last_name": "...", "email": "..." }` (the two names are empty for accounts created without them)  
- **PATCH body:** any of `username`, `email`, `first_name`, `last_name` (the app sends only `username` and `email`; names that are not sent stay as they are) → `{ "message": "Profile updated successfully!" }`  
- **Errors:** `400` (name or email taken, invalid email), `401` (no login), `403` (someone else's profile).

#### Password reset  (public)
- **Request a link:** `POST /reset_password_request/` with `{ "email": "user1@example.com" }`  
  → `200` link sent, `404` unknown email, `502` the email could not be sent.  
- **Set a new password:** `POST /reset_password/` with `{ "email": "...", "token": "...", "password": "..." }`  
  → `200` done; `400` token missing, wrong, used or expired, or password too weak; `404` unknown email.

### Lists
#### Get Lists by user (Home)
- **URL:** `/grouplists/by-user/{user_id}/`  
- **Method:** `GET`  
- **Description:** Returns the lists the logged-in user owns or that were shared with them (always for the logged-in user).  
- **Response:**  
  ```json
  [
    {
      "id": 1,
      "title": "Weekend groceries",
      "items": "✔️ Milk|✔️ Eggs|Bread|Butter|Coffee",
      "date_created": "2026-10-06",
      "user": 2,
      "is_active": true,
      "picture_rows": [1, 2]
    }
  ]
  ```  
  `picture_rows` lists the rows that have a picture (read-only).

#### Create a List
- **URL:** `/listitem/`  
- **Method:** `POST`  
- **Body:** `{ "title": "Weekend groceries", "items": "Milk|Eggs", "user": 2, "is_active": true }`  
- **Then register the owner:** `POST /grouplists/` with `{ "user": 2, "list_item": 1, "role": "admin", "permission_type": "full_access" }`

#### Get All My Lists
- **URL:** `/listitem/`  (optional `?user_id=`)  
- **Method:** `GET`  
- **Description:** Only lists you own or that were shared with you.

####  **Delete ListItem (Deactivate List)**

- **URL:** `/listitem/{id}/`
- **Method:** `PATCH`
- **Body:** `{ "is_active": false }`
- **Description:** Deactivates a list item instead of deleting it (this is what the app's Delete button does). Needs ownership or Full Access.
- **Hard delete:** `DELETE /listitem/{id}/` removes the row for good; the app does not use it. Same permission rule.

#### **Update ListItem**

- **URL:** `/listitem/{id}/`
- **Method:** `PATCH` (or `PUT`)
- **Description:** Updates an existing list item. Needs ownership or Full Access (`403` for Read-Only members, `404` for strangers).
- **Request Body:**
  ```json
  {
    "title": "Updated Shopping List",
    "items": "Apples|Bananas"
  }
  ```
- **Response:**
  ```json
  {
    "id": 1,
    "title": "Updated Shopping List",
    "items": "Apples|Bananas",
    "date_created": "2026-10-06",
    "user": 2,
    "is_active": true,
    "picture_rows": []
  }
  ```

####  **Get the permission of a user on a list**

- **URL:** `/grouplists/permission_type/?user_id={id}&list_item_id={id}`
- **Method:** `GET`
- **Response (200):** `{ "permission_type": "full_access" }` (or `read_only`); `404` if the user has no access.

### Sharing
####  **Share List with User by Email**

- **Steps:** 1) `GET /get_user_info/{email}/` returns the person's `id`. 2) `POST /grouplists/` to share.
- **URL:** `/grouplists/`
- **Method:** `POST`
- **Description:** Adds a person to a list with a permission. Only the list's owner or people with Full Access may do this (`403` otherwise).
- **Request Body:**
  ```json
  {
    "user": 5,
    "list_item": 1,
    "role": "member",
    "permission_type": "read_only"  // or "full_access"
  }
  ```
- **Response (201):**
  ```json
  {
    "message": "GroupList created successfully",
    "data": { "id": 7, "user": 5, "list_item": 1, "role": "member", "permission_type": "read_only" }
  }
  ```

### Pictures
- **Save a list's pictures (used by the app):** `POST /listitemimages/sync_images/` (multipart) with  
  `list_item_id`, `keep` (JSON list `[{"id": 12, "index": 0}]` of existing pictures that stay, with the row each one should be on after saving) and 
  any number of `images`, each a JSON string `{"uri": "<base64 image>", "fileName": "...", "mimeType": "image/png", "index": 2}`.  
  Existing pictures that are not in `keep` are removed (a replaced picture is simply one that is not kept plus a new one for the same row).  
  Everything is checked first (permission, that every kept picture belongs to this list, that new files are real JPEG, PNG or WebP pictures within the limits (8 MB and 40 megapixels each, 200 per save), one picture per row, 
  rows that exist). The records change inside **one database transaction** and old files are deleted only after it succeeds, so it is **all or nothing**.  
  → `200` with `{ "images": [ { "id": 1, "url": "/images/list_item_images/abc.png", "index": 0 } ] }`; errors: `400` (invalid picture or layout), `403` (no edit rights), 
  `404` (no such list), `413` (picture too large), `500` (nothing was changed).  
- **List the pictures of a list:** `GET /listitemimages/{list_id}/get_images_for_list_item/` (**public**) → `{ "images": [ { "id": 1, "url": "/images/list_item_images/photo.png", "index": 0 } ] }`.  
- **Files:** `GET /images/<path>` serves an uploaded file (public).  
- **Older endpoints, kept for older app versions:** `POST /listitemimages/upload_images/` (add pictures) and `POST /listitemimages/update_images/` (re-index). Both need edit rights.  
- The generic picture endpoints (`/listitemimages/`, `/listitemimages/{id}/`) only show and change pictures of lists you can access, and changes need edit rights.

### Customization
- **Save background:** `POST /customizations/` with `{ "background_image_id": 3 }` → `201` created / `200` updated.  
- **Read background:** `GET /customizations/get_user_customization/`.  
- Each user only ever sees their own.

## Workflow

1. **Share a List by Email:**
   - The app looks the person up with `/get_user_info/{email}/`; a `404` means they must join Lista first.
   - It then saves the share with `POST /grouplists/` and the chosen permission (`read_only` or `full_access`).
   
2. **Get Shared Lists:**
   - When the shared user opens Home (`/grouplists/by-user/{id}/`), the shared lists appear with their own; the permission decides whether they can edit.

3. **Update Share Permissions:**
   - Choose the permission when sharing. Changing or removing a share after the fact is on the roadmap; the generic share endpoints are 
     intentionally not exposed.

 * This allows flexibility in how lists are shared and managed between users while allowing the user to set different levels of permissions.
