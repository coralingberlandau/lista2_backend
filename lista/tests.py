"""
End-to-end tests for the Lista API.

They call the backend exactly the way the app does (same URLs, same request bodies,
same Authorization header), so a green run means the main flows still work:
registration, login and token refresh, lists (create / update / soft delete), sharing
and permissions, images, customization, profile and password reset.

Run with:  python manage.py test
"""
import base64
import io
import json
import re
import shutil
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

# A 1x1 transparent PNG, base64 encoded (what the app sends for each image).
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)

PASSWORD = "Test1234!"


def register(client, name):
    """Register a user the way the Register screen does; returns the response data."""
    response = client.post('/register/', {
        'username': name, 'first_name': name, 'last_name': 'Tester',
        'email': f'{name}@example.com', 'password': PASSWORD,
    }, format='json')
    assert response.status_code == 201, response.content
    return response.json()


def authed(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


class ApiTestCase(TestCase):
    """Creates an owner, a friend with full access, a friend with view-only, a stranger."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        anon = APIClient()
        self.owner_data = register(anon, 'owner')
        self.editor_data = register(anon, 'editor')
        self.viewer_data = register(anon, 'viewer')
        self.stranger_data = register(anon, 'stranger')
        self.owner = authed(self.owner_data['access'])
        self.editor = authed(self.editor_data['access'])
        self.viewer = authed(self.viewer_data['access'])
        self.stranger = authed(self.stranger_data['access'])
        self.anon = anon

    def make_list(self, title='Groceries', items='Milk|Eggs'):
        """Create a list like the Create List screen: POST /listitem/ then /grouplists/."""
        uid = self.owner_data['user_id']
        response = self.owner.post('/listitem/', {
            'title': title, 'items': items, 'user': uid, 'is_active': True}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        list_id = response.json()['id']
        response = self.owner.post('/grouplists/', {
            'user': uid, 'list_item': list_id, 'role': 'admin',
            'permission_type': 'full_access'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return list_id

    def share(self, list_id, data, permission):
        """Share like the Share box: look the user up by email, then POST /grouplists/."""
        email = f"{data['username']}@example.com"
        lookup = self.owner.get(f'/get_user_info/{email}/')
        self.assertEqual(lookup.status_code, 200)
        response = self.owner.post('/grouplists/', {
            'user': lookup.json()['id'], 'list_item': list_id, 'role': 'member',
            'permission_type': permission}, format='json')
        self.assertEqual(response.status_code, 201, response.content)


class AuthTests(ApiTestCase):
    def test_register_returns_tokens_and_a_normal_user(self):
        data = register(self.anon, 'newbie')
        self.assertEqual(data['username'], 'newbie')
        self.assertTrue(data['access'])
        self.assertTrue(data['refresh'])
        user = User.objects.get(username='newbie')
        self.assertFalse(user.is_staff)  # new accounts must not get admin-site access
        self.assertFalse(user.is_superuser)

    def test_register_rejects_duplicates_and_missing_fields(self):
        base = {'first_name': 'a', 'last_name': 'b', 'password': PASSWORD}
        r = self.anon.post('/register/', {**base, 'username': 'owner',
                                          'email': 'x@example.com'}, format='json')
        self.assertEqual((r.status_code, r.json()['error']), (400, 'Username already exists.'))
        r = self.anon.post('/register/', {**base, 'username': 'someone',
                                          'email': 'owner@example.com'}, format='json')
        self.assertEqual((r.status_code, r.json()['error']), (400, 'Email already in use.'))
        r = self.anon.post('/register/', {'username': 'only-name'}, format='json')
        self.assertEqual(r.status_code, 400)  # used to be a 500 error

    def test_register_refuses_weak_passwords_with_a_clear_message(self):
        base = {'first_name': 'A', 'last_name': 'B', 'email': 'weak@example.com'}
        cases = {
            'short': ('Ab1!', 'at least 8 characters'),
            'common': ('password', 'too common'),
            'digits only': ('83920174', 'entirely numeric'),
            'like the username': ('weakling1', 'too similar'),
        }
        for label, (password, expected) in cases.items():
            r = self.anon.post('/register/', {**base, 'username': 'weakling',
                                              'password': password}, format='json')
            self.assertEqual(r.status_code, 400, label)
            self.assertIn(expected, r.json()['error'], label)
        self.assertFalse(User.objects.filter(username='weakling').exists())
        # A decent password for the same details is accepted.
        r = self.anon.post('/register/', {**base, 'username': 'weakling',
                                          'password': 'Purple-Giraffe-42'}, format='json')
        self.assertEqual(r.status_code, 201)

    def test_existing_users_with_old_weak_passwords_can_still_log_in(self):
        user = User.objects.get(username='owner')
        user.set_password('1')  # set_password does not run the rules, like old accounts
        user.save()
        r = self.anon.post('/login/', {'username': 'owner', 'password': '1'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_login_success_and_failure(self):
        r = self.anon.post('/login/', {'username': 'owner', 'password': PASSWORD}, format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['access'] and body['refresh'])
        claims = json.loads(base64.urlsafe_b64decode(body['access'].split('.')[1] + '=='))
        self.assertEqual(claims['user_id'], self.owner_data['user_id'])
        self.assertEqual(claims['username'], 'owner')
        r = self.anon.post('/login/', {'username': 'owner', 'password': 'wrong'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_token_refresh_rotates_and_old_token_stops_working(self):
        login = self.anon.post(
            '/login/', {'username': 'owner', 'password': PASSWORD}, format='json').json()
        r = self.anon.post('/token/refresh/', {'refresh': login['refresh']}, format='json')
        self.assertEqual(r.status_code, 200)
        fresh = r.json()
        self.assertTrue(fresh['access'] and fresh['refresh'])
        self.assertNotEqual(fresh['refresh'], login['refresh'])
        # The new access token works on a protected endpoint.
        ok = authed(fresh['access']).get(f"/grouplists/by-user/{self.owner_data['user_id']}/")
        self.assertEqual(ok.status_code, 200)
        # The old refresh token was rotated out and can't be reused.
        again = self.anon.post('/token/refresh/', {'refresh': login['refresh']}, format='json')
        self.assertEqual(again.status_code, 401)
        bad = self.anon.post('/token/refresh/', {'refresh': 'garbage'}, format='json')
        self.assertEqual(bad.status_code, 401)

    def test_protected_endpoints_reject_anonymous_users(self):
        for method, url in [
            ('get', '/listitem/'), ('get', '/listitem/1/'), ('get', '/grouplists/by-user/1/'),
            ('get', '/grouplists/'), ('get', '/listitemimages/'),
            ('get', '/customizations/get_user_customization/'),
            ('get', '/get_user_info/owner@example.com/'),
        ]:
            r = getattr(self.anon, method)(url)
            self.assertEqual(r.status_code, 401, f'{method} {url} should need login')
        r = self.anon.post('/listitem/', {'title': 'x'}, format='json')
        self.assertEqual(r.status_code, 401)
        r = self.anon.post('/grouplists/', {}, format='json')
        self.assertEqual(r.status_code, 401)
        r = self.anon.post('/listitemimages/upload_images/', {}, format='multipart')
        self.assertEqual(r.status_code, 401)

    def test_removed_openai_and_debug_endpoints_are_gone(self):
        for url in ['/recommendations/1/', '/index/', '/test/', '/priverty/']:
            self.assertEqual(self.owner.get(url).status_code, 404, url)


class LogSafetyTests(ApiTestCase):
    def test_log_file_never_contains_tokens_or_authorization_headers(self):
        from lista import logging_utils
        before = 0
        try:
            with open(logging_utils.LOG_FILE, encoding='utf-8') as f:
                before = len(f.read())
        except FileNotFoundError:
            pass
        self.make_list()  # logs in, creates a list, and sends an Authorization header
        self.anon.post('/login/', {'username': 'owner', 'password': PASSWORD}, format='json')
        with open(logging_utils.LOG_FILE, encoding='utf-8') as f:
            new_text = f.read()[before:]
        self.assertTrue(new_text)  # something was logged
        self.assertNotIn('eyJ', new_text)      # no JWT of any kind
        self.assertNotIn('Bearer ', new_text)  # no Authorization header value
        self.assertNotIn(PASSWORD, new_text)


class ListTests(ApiTestCase):
    def test_create_list_and_see_it_on_home(self):
        list_id = self.make_list()
        r = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/")
        self.assertEqual(r.status_code, 200)
        titles = [item['title'] for item in r.json()]
        self.assertEqual(titles, ['Groceries'])
        self.assertTrue(r.json()[0]['is_active'])
        self.assertEqual(r.json()[0]['id'], list_id)

    def test_permission_type_endpoint_used_by_the_edit_screen(self):
        list_id = self.make_list()
        r = self.owner.get('/grouplists/permission_type/', {
            'user_id': self.owner_data['user_id'], 'list_item_id': list_id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['permission_type'], 'full_access')

    def test_update_list_title_and_items(self):
        list_id = self.make_list()
        r = self.owner.patch(f'/listitem/{list_id}/',
                             {'title': 'Weekend', 'items': '✔️ Milk|Bread'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        home = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        self.assertEqual((home[0]['title'], home[0]['items']), ('Weekend', '✔️ Milk|Bread'))

    def test_list_with_a_title_and_no_items_can_be_saved(self):
        # Creating the list first and filling it in later is allowed (the title stays required).
        list_id = self.make_list(title='Trip ideas', items='')
        home = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        self.assertEqual((home[0]['title'], home[0]['items']), ('Trip ideas', ''))
        # An existing list can also be emptied and filled again.
        r = self.owner.patch(f'/listitem/{list_id}/', {'items': 'Passport|Tickets'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.owner.patch(f'/listitem/{list_id}/', {'items': ''}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['items'], '')

    def test_a_list_still_needs_a_title(self):
        uid = self.owner_data['user_id']
        r = self.owner.post('/listitem/', {
            'title': '', 'items': 'Milk', 'user': uid, 'is_active': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('title', r.json())

    def test_delete_is_a_soft_delete_and_keeps_the_data(self):
        list_id = self.make_list()
        r = self.owner.patch(f'/listitem/{list_id}/', {'is_active': False}, format='json')
        self.assertEqual(r.status_code, 200)
        home = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        # The app filters inactive lists out; the row itself is still there.
        self.assertEqual([item['is_active'] for item in home], [False])
        from lista.models import ListItem
        self.assertTrue(ListItem.objects.filter(id=list_id).exists())

    def test_strangers_cannot_see_or_change_someone_elses_list(self):
        list_id = self.make_list()
        self.assertEqual(self.stranger.get(f'/listitem/{list_id}/').status_code, 404)
        r = self.stranger.patch(f'/listitem/{list_id}/', {'title': 'hacked'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.stranger.get('/listitem/').json(), [])
        # ...and cannot add themselves to it.
        r = self.stranger.post('/grouplists/', {
            'user': self.stranger_data['user_id'], 'list_item': list_id, 'role': 'member',
            'permission_type': 'full_access'}, format='json')
        self.assertEqual(r.status_code, 403)
        # Title unchanged.
        mine = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        self.assertEqual(mine[0]['title'], 'Groceries')

    def test_create_grouplist_with_a_bad_list_id_is_a_400_not_a_crash(self):
        r = self.owner.post('/grouplists/', {
            'user': self.owner_data['user_id'], 'list_item': 'abc', 'role': 'admin',
            'permission_type': 'full_access'}, format='json')
        self.assertEqual(r.status_code, 400)


class HardeningTests(ApiTestCase):
    """The generic endpoints the app never uses must not be a way around the permissions."""

    def test_view_only_friend_cannot_hard_delete_a_list(self):
        list_id = self.make_list()
        self.share(list_id, self.viewer_data, 'read_only')
        self.assertEqual(self.viewer.delete(f'/listitem/{list_id}/').status_code, 403)
        self.assertEqual(self.stranger.delete(f'/listitem/{list_id}/').status_code, 404)
        from lista.models import ListItem
        self.assertTrue(ListItem.objects.filter(id=list_id).exists())
        self.assertEqual(self.owner.delete(f'/listitem/{list_id}/').status_code, 204)

    def test_view_only_friend_cannot_change_or_delete_images_through_generic_endpoints(self):
        list_id = self.make_list()
        payload = json.dumps({'uri': PNG_B64, 'fileName': 'p', 'mimeType': 'image/png', 'index': 0})
        self.owner.post('/listitemimages/upload_images/',
                        {'list_item': list_id, 'images': [payload]}, format='multipart')
        self.share(list_id, self.viewer_data, 'read_only')
        from lista.models import ListItemImage
        image_id = ListItemImage.objects.get().id
        self.assertEqual(self.viewer.delete(f'/listitemimages/{image_id}/').status_code, 403)
        self.assertEqual(self.viewer.patch(f'/listitemimages/{image_id}/', {'index': 5},
                                           format='json').status_code, 403)
        self.assertTrue(ListItemImage.objects.filter(id=image_id).exists())

    def test_share_rows_cannot_be_browsed_changed_or_removed(self):
        list_id = self.make_list()
        self.share(list_id, self.viewer_data, 'read_only')
        from lista.models import GroupList
        row = GroupList.objects.get(user_id=self.viewer_data['user_id'])
        for method, url in [('get', '/grouplists/'), ('get', f'/grouplists/{row.id}/'),
                            ('delete', f'/grouplists/{row.id}/'),
                            ('patch', f'/grouplists/{row.id}/'), ('put', f'/grouplists/{row.id}/')]:
            r = getattr(self.stranger, method)(url)
            self.assertIn(r.status_code, (404, 405), f'{method} {url}')
        self.assertTrue(GroupList.objects.filter(id=row.id).exists())


class SharingTests(ApiTestCase):
    def test_share_lookup_returns_only_safe_fields(self):
        r = self.owner.get('/get_user_info/editor@example.com/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {'id', 'username'})
        self.assertEqual(r.json()['id'], self.editor_data['user_id'])
        self.assertNotIn('password', r.content.decode())

    def test_share_lookup_unknown_email_is_404(self):
        r = self.owner.get('/get_user_info/nobody@example.com/')
        self.assertEqual(r.status_code, 404)

    def test_full_access_friend_sees_and_edits_the_list(self):
        list_id = self.make_list()
        self.share(list_id, self.editor_data, 'full_access')
        # The friend's Home shows the list.
        home = self.editor.get(f"/grouplists/by-user/{self.editor_data['user_id']}/").json()
        self.assertEqual([item['title'] for item in home], ['Groceries'])
        perm = self.editor.get('/grouplists/permission_type/', {
            'user_id': self.editor_data['user_id'], 'list_item_id': list_id}).json()
        self.assertEqual(perm['permission_type'], 'full_access')
        r = self.editor.patch(f'/listitem/{list_id}/', {'title': 'Edited by friend'},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)
        # The owner still sees the list on their own Home screen afterwards.
        mine = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        self.assertEqual([item['title'] for item in mine], ['Edited by friend'])

    def test_full_access_friend_can_share_onward(self):
        list_id = self.make_list()
        self.share(list_id, self.editor_data, 'full_access')
        lookup = self.editor.get('/get_user_info/viewer@example.com/').json()
        r = self.editor.post('/grouplists/', {
            'user': lookup['id'], 'list_item': list_id, 'role': 'member',
            'permission_type': 'read_only'}, format='json')
        self.assertEqual(r.status_code, 201)

    def test_view_only_friend_can_read_but_not_change_or_share(self):
        list_id = self.make_list()
        self.share(list_id, self.viewer_data, 'read_only')
        home = self.viewer.get(f"/grouplists/by-user/{self.viewer_data['user_id']}/").json()
        self.assertEqual(len(home), 1)
        self.assertEqual(self.viewer.get(f'/listitem/{list_id}/').status_code, 200)
        r = self.viewer.patch(f'/listitem/{list_id}/', {'title': 'nope'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.viewer.patch(f'/listitem/{list_id}/', {'is_active': False}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.viewer.post('/grouplists/', {
            'user': self.viewer_data['user_id'], 'list_item': list_id, 'role': 'member',
            'permission_type': 'full_access'}, format='json')
        self.assertEqual(r.status_code, 403)


class ImageTests(ApiTestCase):
    def upload(self, client, list_id, name='photo', index=0):
        payload = json.dumps({
            'uri': PNG_B64, 'fileName': name, 'mimeType': 'image/png', 'index': index})
        return client.post('/listitemimages/upload_images/',
                           {'list_item': list_id, 'images': [payload]}, format='multipart')

    def test_upload_list_fetch_and_download_an_image(self):
        list_id = self.make_list()
        r = self.upload(self.owner, list_id)
        self.assertEqual(r.status_code, 201, r.content)
        # The app fetches images WITHOUT a token, so this must stay public.
        r = self.anon.get(f'/listitemimages/{list_id}/get_images_for_list_item/')
        self.assertEqual(r.status_code, 200)
        images = r.json()['images']
        self.assertEqual(len(images), 1)
        url = images[0]['url']
        self.assertTrue(url.startswith('/images/'), url)
        # And the picture itself must be downloadable (served even with DEBUG off).
        r = self.anon.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content)[:4], b'\x89PNG')

    def test_no_images_message(self):
        list_id = self.make_list()
        r = self.anon.get(f'/listitemimages/{list_id}/get_images_for_list_item/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['images'], [])

    def test_upload_requires_login_and_edit_rights(self):
        list_id = self.make_list()
        self.assertEqual(self.upload(self.anon, list_id).status_code, 401)
        self.assertEqual(self.upload(self.stranger, list_id).status_code, 403)
        self.share(list_id, self.viewer_data, 'read_only')
        self.assertEqual(self.upload(self.viewer, list_id).status_code, 403)
        self.share(list_id, self.editor_data, 'full_access')
        self.assertEqual(self.upload(self.editor, list_id).status_code, 201)

    def test_upload_without_a_file_name_does_not_crash(self):
        list_id = self.make_list()
        r = self.upload(self.owner, list_id, name='')
        self.assertEqual(r.status_code, 201, r.content)

    def test_upload_larger_than_the_old_django_default_is_accepted(self):
        # A resized photo is small, but a normal phone photo can be a few MB. This payload is
        # about 3 MB of text, above Django's default 2.5 MB limit that used to refuse it.
        from django.conf import settings
        self.assertEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 10 * 1024 * 1024)
        list_id = self.make_list()
        big = base64.b64encode(b'\x89PNG' + bytes(2300 * 1024)).decode()
        payload = json.dumps({
            'uri': big, 'fileName': 'big', 'mimeType': 'image/png', 'index': 0})
        self.assertGreater(len(payload), 2.5 * 1024 * 1024)
        r = self.owner.post('/listitemimages/upload_images/',
                            {'list_item': list_id, 'images': [payload]}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content[:200])
        r = self.anon.get(f'/listitemimages/{list_id}/get_images_for_list_item/')
        self.assertEqual(len(r.json()['images']), 1)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=2000)
    def test_upload_over_the_limit_gives_a_clear_message_and_saves_nothing(self):
        list_id = self.make_list()
        payload = json.dumps({
            'uri': 'A' * 5000, 'fileName': 'huge', 'mimeType': 'image/png', 'index': 0})
        r = self.owner.post('/listitemimages/upload_images/',
                            {'list_item': list_id, 'images': [payload]}, format='multipart')
        self.assertEqual(r.status_code, 413)
        self.assertIn('too large', r.json()['error'])
        from lista.models import ListItemImage
        self.assertEqual(ListItemImage.objects.count(), 0)
        # The same permission rules still apply before the size is looked at.
        self.assertEqual(self.anon.post('/listitemimages/upload_images/',
                                        {'list_item': list_id, 'images': [payload]},
                                        format='multipart').status_code, 401)

    def test_update_images_endpoint(self):
        list_id = self.make_list()
        self.upload(self.owner, list_id, name='first', index=0)
        self.upload(self.owner, list_id, name='second', index=1)
        # Like the app after removing image 0: the later image (index 1) shifts down to 0.
        r = self.owner.post('/listitemimages/update_images/', {
            'list_item_id': list_id, 'updatedImagesIndex[]': ['1'],
            'deletedImagesIndex[]': ['0']}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        from lista.models import ListItemImage
        self.assertEqual(sorted(ListItemImage.objects.values_list('index', flat=True)), [0, 0])
        self.assertEqual(self.stranger.post('/listitemimages/update_images/', {
            'list_item_id': list_id}, format='multipart').status_code, 403)
        self.assertEqual(self.anon.post('/listitemimages/update_images/', {
            'list_item_id': list_id}, format='multipart').status_code, 401)

    def test_strangers_cannot_list_or_delete_images_through_the_generic_endpoints(self):
        list_id = self.make_list()
        self.upload(self.owner, list_id)
        self.assertEqual(self.stranger.get('/listitemimages/').json(), [])
        from lista.models import ListItemImage
        image_id = ListItemImage.objects.get().id
        self.assertEqual(self.stranger.delete(f'/listitemimages/{image_id}/').status_code, 404)
        self.assertTrue(ListItemImage.objects.filter(id=image_id).exists())


class CustomizationAndProfileTests(ApiTestCase):
    def test_background_customization_roundtrip(self):
        empty = self.owner.get('/customizations/get_user_customization/')
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()['data'], {})
        r = self.owner.post('/customizations/', {'background_image_id': 3}, format='json')
        self.assertEqual(r.status_code, 201)
        r = self.owner.post('/customizations/', {'background_image_id': 5}, format='json')
        self.assertEqual(r.status_code, 200)
        got = self.owner.get('/customizations/get_user_customization/').json()
        self.assertEqual(str(got['data']['background_image_id']), '5')
        self.assertEqual(self.owner.post('/customizations/', {}, format='json').status_code, 400)

    def test_customizations_are_private(self):
        self.owner.post('/customizations/', {'background_image_id': 3}, format='json')
        self.assertEqual(self.stranger.get('/customizations/').json(), [])

    def test_edit_profile_with_the_login_token(self):
        uid = self.owner_data['user_id']
        r = self.owner.get(f'/user/{uid}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {'username', 'first_name', 'last_name', 'email'})
        r = self.owner.patch(f'/user/{uid}/', {
            'username': 'owner', 'first_name': 'New', 'last_name': 'Name',
            'email': 'owner@example.com'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.get(id=uid).first_name, 'New')
        r = self.owner.patch(f'/user/{uid}/', {'username': 'editor'}, format='json')
        self.assertEqual(r.status_code, 400)  # name already taken
        r = self.owner.patch(f'/user/{uid}/', {'email': 'editor@example.com'}, format='json')
        self.assertEqual(r.status_code, 400)  # email already taken

    def test_an_invalid_email_in_the_profile_is_a_clean_400(self):
        uid = self.owner_data['user_id']
        r = self.owner.patch(f'/user/{uid}/', {'email': 'not-an-email'}, format='json')
        self.assertEqual(r.status_code, 400)  # used to crash with a server error
        self.assertEqual(r.json()['error'], 'Invalid email format.')

    def test_profiles_are_private(self):
        uid = self.owner_data['user_id']
        self.assertEqual(self.anon.get(f'/user/{uid}/').status_code, 401)
        self.assertEqual(self.anon.patch(f'/user/{uid}/', {'first_name': 'x'},
                                         format='json').status_code, 401)
        self.assertEqual(self.stranger.get(f'/user/{uid}/').status_code, 403)
        r = self.stranger.patch(f'/user/{uid}/', {'first_name': 'hacked'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(User.objects.get(id=uid).first_name, 'owner')


class RegistrationWithoutNamesTests(ApiTestCase):
    """
    The app asks only for a username, an email and a password: first and last name are
    optional. These tests protect that, and make sure people who do have names are not
    affected (their names are kept, and older versions of the app that still send them work).
    """

    def register_without_names(self, name='nameless'):
        response = self.anon.post('/register/', {
            'username': name, 'email': f'{name}@example.com', 'password': PASSWORD,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_registration_works_without_first_and_last_name(self):
        data = self.register_without_names()
        self.assertEqual(data['username'], 'nameless')
        self.assertTrue(data['access'])
        self.assertTrue(data['refresh'])
        user = User.objects.get(username='nameless')
        self.assertEqual((user.first_name, user.last_name), ('', ''))
        self.assertFalse(user.is_staff)

    def test_a_user_without_names_can_log_in_see_home_and_edit_the_profile(self):
        data = self.register_without_names()
        uid = data['user_id']
        me = authed(data['access'])

        # Login with the username and password, exactly as the Login screen does.
        r = self.anon.post('/login/', {'username': 'nameless', 'password': PASSWORD}, format='json')
        self.assertEqual(r.status_code, 200)

        # The Home screen's request works and starts empty.
        r = me.get(f'/grouplists/by-user/{uid}/')
        self.assertEqual((r.status_code, r.json()), (200, []))

        # Edit Profile reads the profile; the names simply come back empty.
        r = me.get(f'/user/{uid}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'username': 'nameless', 'first_name': '',
                                    'last_name': '', 'email': 'nameless@example.com'})

        # Edit Profile saves only the username and email, and the names stay empty.
        r = me.patch(f'/user/{uid}/', {'username': 'renamed', 'email': 'renamed@example.com'},
                     format='json')
        self.assertEqual(r.status_code, 200)
        user = User.objects.get(id=uid)
        self.assertEqual((user.username, user.email), ('renamed', 'renamed@example.com'))
        self.assertEqual((user.first_name, user.last_name), ('', ''))

        # Other people can still find them by email when sharing a list.
        r = self.owner.get('/get_user_info/renamed@example.com/')
        self.assertEqual((r.status_code, r.json()), (200, {'id': uid, 'username': 'renamed'}))

    def test_users_with_names_keep_them_when_the_profile_is_saved_without_names(self):
        uid = self.owner_data['user_id']  # registered with a first and a last name
        before = User.objects.get(id=uid)
        self.assertEqual((before.first_name, before.last_name), ('owner', 'Tester'))
        r = self.owner.patch(f'/user/{uid}/', {'username': 'owner', 'email': 'owner@example.com'},
                             format='json')
        self.assertEqual(r.status_code, 200)
        after = User.objects.get(id=uid)
        self.assertEqual((after.first_name, after.last_name), ('owner', 'Tester'))
        # ...and the profile still returns them.
        body = self.owner.get(f'/user/{uid}/').json()
        self.assertEqual((body['first_name'], body['last_name']), ('owner', 'Tester'))

    def test_older_versions_of_the_app_that_still_send_names_are_accepted(self):
        r = self.anon.post('/register/', {
            'username': 'oldclient', 'first_name': 'Old', 'last_name': 'Client',
            'email': 'oldclient@example.com', 'password': PASSWORD}, format='json')
        self.assertEqual(r.status_code, 201)
        user = User.objects.get(username='oldclient')
        self.assertEqual((user.first_name, user.last_name), ('Old', 'Client'))

    def test_registration_still_needs_a_username_an_email_and_a_password(self):
        base = {'username': 'incomplete', 'email': 'incomplete@example.com', 'password': PASSWORD}
        for missing in ('username', 'email', 'password'):
            body = {key: value for key, value in base.items() if key != missing}
            r = self.anon.post('/register/', body, format='json')
            self.assertEqual(r.status_code, 400, missing)
        self.assertFalse(User.objects.filter(username='incomplete').exists())


class FakeBrevoResponse:
    """Stands in for the HTTP response of Brevo's send-email API."""
    def __init__(self, status=201):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


BREVO_URLOPEN = 'lista.views.urllib.request.urlopen'


@override_settings(BREVO_API_KEY='test-key')
class PasswordResetTests(ApiTestCase):
    def request_link(self, email='owner@example.com'):
        """Ask for a reset email (Brevo is replaced by a stand-in) and return the link in it."""
        with mock.patch(BREVO_URLOPEN, return_value=FakeBrevoResponse()) as urlopen:
            r = self.anon.post('/reset_password_request/', {'email': email}, format='json')
            self.assertEqual(r.status_code, 200)
            sent = urlopen.call_args.args[0]
        payload = json.loads(sent.data)
        self.assertEqual(sent.full_url, 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(sent.get_header('Api-key'), 'test-key')
        self.assertEqual(payload['to'], [{'email': email}])
        self.assertEqual(payload['sender']['email'], 'listaassistance@gmail.com')
        match = re.search(r'/change-password\?(\S+)', payload['textContent'])
        self.assertIsNotNone(match, payload['textContent'])
        self.last_text = payload['textContent']
        return parse_qs(match.group(1))

    def test_request_sends_an_email_link_and_unknown_email_is_404(self):
        link = self.request_link()
        self.assertEqual(link['email'], ['owner@example.com'])
        self.assertTrue(link['token'][0])
        self.assertIn('expires in one hour', self.last_text)
        with mock.patch(BREVO_URLOPEN) as urlopen:
            r = self.anon.post('/reset_password_request/',
                               {'email': 'nobody@example.com'}, format='json')
            self.assertEqual(r.status_code, 404)
            r = self.anon.post('/reset_password_request/', {}, format='json')
            self.assertEqual(r.status_code, 400)
            urlopen.assert_not_called()  # nothing is sent for these

    def test_request_reports_failure_when_the_email_could_not_be_sent(self):
        body = {'email': 'owner@example.com'}
        rejected = HTTPError('https://api.brevo.com', 401, 'Unauthorized', {}, io.BytesIO(b'{}'))
        for failure in (rejected, URLError('connection blocked'), OSError('timed out')):
            with mock.patch(BREVO_URLOPEN, side_effect=failure):
                r = self.anon.post('/reset_password_request/', body, format='json')
            self.assertEqual(r.status_code, 502, failure)
            self.assertIn("couldn't send", r.json()['error'])
        with mock.patch(BREVO_URLOPEN, return_value=FakeBrevoResponse(500)):
            r = self.anon.post('/reset_password_request/', body, format='json')
        self.assertEqual(r.status_code, 502)

    @override_settings(BREVO_API_KEY='')
    def test_request_fails_cleanly_when_no_api_key_is_configured(self):
        with mock.patch(BREVO_URLOPEN) as urlopen:
            r = self.anon.post('/reset_password_request/',
                               {'email': 'owner@example.com'}, format='json')
            urlopen.assert_not_called()
        self.assertEqual(r.status_code, 502)

    def test_the_api_key_never_reaches_the_log_file(self):
        from lista import logging_utils
        before = 0
        try:
            with open(logging_utils.LOG_FILE, encoding='utf-8') as f:
                before = len(f.read())
        except FileNotFoundError:
            pass
        self.request_link()
        with open(logging_utils.LOG_FILE, encoding='utf-8') as f:
            new_text = f.read()[before:]
        self.assertNotIn('test-key', new_text)

    def test_reset_with_the_emailed_token_then_log_in_with_the_new_password(self):
        link = self.request_link()
        r = self.anon.post('/reset_password/', {
            'email': link['email'][0], 'token': link['token'][0],
            'password': 'Brand-new-1!'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        old = self.anon.post('/login/', {'username': 'owner', 'password': PASSWORD},
                             format='json')
        self.assertEqual(old.status_code, 401)
        new = self.anon.post('/login/', {'username': 'owner', 'password': 'Brand-new-1!'},
                             format='json')
        self.assertEqual(new.status_code, 200)

    def test_reset_is_refused_without_a_valid_token(self):
        body = {'email': 'owner@example.com', 'password': 'Hacked-1!'}
        r = self.anon.post('/reset_password/', body, format='json')  # no token at all
        self.assertEqual(r.status_code, 400)
        r = self.anon.post('/reset_password/', {**body, 'token': 'not-a-real-token'},
                           format='json')
        self.assertEqual(r.status_code, 400)
        # A token for a different account does not work either.
        other = self.request_link('editor@example.com')
        r = self.anon.post('/reset_password/', {**body, 'token': other['token'][0]},
                           format='json')
        self.assertEqual(r.status_code, 400)
        # The password was never changed.
        ok = self.anon.post('/login/', {'username': 'owner', 'password': PASSWORD},
                            format='json')
        self.assertEqual(ok.status_code, 200)

    def test_a_weak_new_password_is_refused_without_using_up_the_link(self):
        link = self.request_link()
        body = {'email': link['email'][0], 'token': link['token'][0]}
        weak = self.anon.post('/reset_password/', {**body, 'password': '12345'}, format='json')
        self.assertEqual(weak.status_code, 400)
        self.assertIn('at least 8 characters', weak.json()['error'])
        # The password was not changed and the same link still works with a stronger one.
        still = self.anon.post('/login/', {'username': 'owner', 'password': PASSWORD},
                               format='json')
        self.assertEqual(still.status_code, 200)
        link2 = self.request_link()
        ok = self.anon.post('/reset_password/', {
            'email': link2['email'][0], 'token': link2['token'][0],
            'password': 'Sturdy-Pelican-77'}, format='json')
        self.assertEqual(ok.status_code, 200, ok.content)

    def test_a_reset_link_works_only_once(self):
        link = self.request_link()
        body = {'email': link['email'][0], 'token': link['token'][0], 'password': 'Once-only-1!'}
        self.assertEqual(self.anon.post('/reset_password/', body, format='json').status_code, 200)
        again = self.anon.post('/reset_password/', {**body, 'password': 'Second-try-1!'},
                               format='json')
        self.assertEqual(again.status_code, 400)

    def test_an_expired_link_is_refused(self):
        link = self.request_link()
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            r = self.anon.post('/reset_password/', {
                'email': link['email'][0], 'token': link['token'][0],
                'password': 'Too-late-1!'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_reset_for_an_unknown_email_is_404_and_missing_fields_400(self):
        r = self.anon.post('/reset_password/', {
            'email': 'nobody@example.com', 'token': 'x', 'password': 'x'}, format='json')
        self.assertEqual(r.status_code, 404)
        r = self.anon.post('/reset_password/', {'email': 'owner@example.com'}, format='json')
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# Pictures: rows with pictures, all-or-nothing saving, file cleanup
# ---------------------------------------------------------------------------

def picture_b64(fmt='PNG', size=(12, 8), color=(200, 40, 40)):
    """A small real picture, base64 encoded, the way the app sends it."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format=fmt)
    return base64.b64encode(buffer.getvalue()).decode()


class PictureSavingBase(ApiTestCase):
    def new_picture(self, index, fmt='PNG', name='photo', raw=None, mime=None):
        return json.dumps({
            'uri': raw if raw is not None else picture_b64(fmt),
            'fileName': name,
            'mimeType': mime or f'image/{fmt.lower()}',
            'index': index})

    def sync(self, client, list_id, keep=None, new=None):
        """Send the single 'save the pictures of this list' request, like the app does."""
        # Old picture files are removed after the save is committed; the test runner never
        # commits, so run those after-the-save steps explicitly (like a real commit would).
        with self.captureOnCommitCallbacks(execute=True):
            return client.post('/listitemimages/sync_images/', {
                'list_item_id': list_id,
                'keep': json.dumps(keep or []),
                'images': new or []}, format='multipart')

    def rows(self, list_id):
        from lista.models import ListItemImage
        return {image.index: image for image in ListItemImage.objects.filter(list_item_id=list_id)}

    def file_exists(self, image):
        from django.core.files.storage import default_storage
        return default_storage.exists(image.image.name)


class PictureRowsFieldTests(PictureSavingBase):
    def test_lists_report_which_rows_have_a_picture(self):
        list_id = self.make_list(items='Milk||Eggs')
        home = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        self.assertEqual(home[0]['picture_rows'], [])
        r = self.sync(self.owner, list_id, new=[self.new_picture(2), self.new_picture(1)])
        self.assertEqual(r.status_code, 200, r.content)
        home = self.owner.get(f"/grouplists/by-user/{self.owner_data['user_id']}/").json()
        self.assertEqual(home[0]['picture_rows'], [1, 2])
        mine = self.owner.get('/listitem/').json()
        self.assertEqual(mine[0]['picture_rows'], [1, 2])

    def test_picture_rows_cannot_be_written_by_the_app(self):
        list_id = self.make_list()
        r = self.owner.patch(f'/listitem/{list_id}/', {'picture_rows': [5]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['picture_rows'], [])


class SyncImagesTests(PictureSavingBase):
    def test_add_pictures_to_rows_including_a_row_without_text(self):
        # Row 1 is a blank row (a spacer or a picture-only row) and must keep its picture.
        list_id = self.make_list(items='Milk||Eggs')
        r = self.sync(self.owner, list_id, new=[self.new_picture(0), self.new_picture(1, 'JPEG')])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(i['index'] for i in r.json()['images']), [0, 1])
        rows = self.rows(list_id)
        self.assertEqual(sorted(rows), [0, 1])
        self.assertTrue(all(self.file_exists(i) for i in rows.values()))
        # The picture type is decided by the server from the real file, not by the app.
        self.assertEqual(rows[0].mime_type, 'image/png')
        self.assertEqual(rows[1].mime_type, 'image/jpeg')
        # Stored under a random name, never the name the app sent.
        self.assertNotIn('photo', rows[0].image.name)
        listed = self.anon.get(f'/listitemimages/{list_id}/get_images_for_list_item/').json()['images']
        self.assertEqual(sorted(i['index'] for i in listed), [0, 1])

    def test_replace_a_picture_removes_the_old_one_and_its_file(self):
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        old = self.rows(list_id)[0]
        old_id, old_path = old.id, old.image.name
        r = self.sync(self.owner, list_id, keep=[], new=[self.new_picture(0, 'JPEG')])
        self.assertEqual(r.status_code, 200, r.content)
        rows = self.rows(list_id)
        self.assertEqual(list(rows), [0])
        self.assertNotEqual(rows[0].id, old_id)
        from django.core.files.storage import default_storage
        self.assertFalse(default_storage.exists(old_path))
        self.assertTrue(self.file_exists(rows[0]))

    def test_remove_a_picture(self):
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0), self.new_picture(1)])
        keep_row = self.rows(list_id)[1]
        removed_path = self.rows(list_id)[0].image.name
        r = self.sync(self.owner, list_id, keep=[{'id': keep_row.id, 'index': 1}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(list(self.rows(list_id)), [1])
        from django.core.files.storage import default_storage
        self.assertFalse(default_storage.exists(removed_path))
        self.assertTrue(self.file_exists(self.rows(list_id)[1]))

    def test_deleting_a_row_moves_the_later_pictures_with_their_rows(self):
        list_id = self.make_list(items='A|B|C')
        self.sync(self.owner, list_id, new=[self.new_picture(0), self.new_picture(1), self.new_picture(2)])
        before = self.rows(list_id)
        # The app removed row 0: rows B and C move up to positions 0 and 1; A's picture goes.
        keep = [{'id': before[1].id, 'index': 0}, {'id': before[2].id, 'index': 1}]
        r = self.sync(self.owner, list_id, keep=keep)
        self.assertEqual(r.status_code, 200, r.content)
        after = self.rows(list_id)
        self.assertEqual(sorted(after), [0, 1])
        self.assertEqual(after[0].id, before[1].id)
        self.assertEqual(after[1].id, before[2].id)

    def test_picture_for_a_row_that_does_not_exist_is_refused(self):
        list_id = self.make_list(items='Milk|Eggs')
        r = self.sync(self.owner, list_id, new=[self.new_picture(5)])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.rows(list_id), {})

    def test_two_pictures_for_the_same_row_are_refused_and_nothing_changes(self):
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        existing = self.rows(list_id)[0]
        r = self.sync(self.owner, list_id, keep=[{'id': existing.id, 'index': 0}],
                      new=[self.new_picture(0, 'JPEG')])
        self.assertEqual(r.status_code, 400)
        self.assertEqual([i.id for i in self.rows(list_id).values()], [existing.id])
        self.assertTrue(self.file_exists(existing))

    def test_a_picture_of_another_list_cannot_be_attached(self):
        mine = self.make_list(title='Mine')
        other = self.make_list(title='Other')
        self.sync(self.owner, other, new=[self.new_picture(0)])
        foreign = self.rows(other)[0]
        r = self.sync(self.owner, mine, keep=[{'id': foreign.id, 'index': 0}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.rows(mine), {})
        self.assertEqual(list(self.rows(other)), [0])
        self.assertTrue(self.file_exists(self.rows(other)[0]))

    def test_a_file_that_is_not_a_picture_is_refused_and_the_old_picture_stays(self):
        list_id = self.make_list(items='Milk|Eggs')
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        old = self.rows(list_id)[0]
        junk = base64.b64encode(b'this is just text, not a picture').decode()
        r = self.sync(self.owner, list_id, new=[self.new_picture(0, raw=junk)])
        self.assertEqual(r.status_code, 400)
        self.assertIn('picture', r.json()['error'].lower())
        self.assertEqual(self.rows(list_id)[0].id, old.id)
        self.assertTrue(self.file_exists(old))

    def test_a_picture_that_is_too_big_is_refused_and_the_old_picture_stays(self):
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        old = self.rows(list_id)[0]
        with mock.patch('lista.views.MAX_PICTURE_BYTES', 10):
            r = self.sync(self.owner, list_id, new=[self.new_picture(0, 'JPEG')])
        self.assertEqual(r.status_code, 413)
        self.assertIn('too large', r.json()['error'])
        self.assertEqual(self.rows(list_id)[0].id, old.id)
        self.assertTrue(self.file_exists(old))

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=500)
    def test_a_request_over_the_upload_limit_gives_a_clear_message(self):
        list_id = self.make_list()
        r = self.sync(self.owner, list_id, new=[self.new_picture(0, raw='A' * 2000)])
        self.assertEqual(r.status_code, 413)
        self.assertIn('too large', r.json()['error'])

    def test_a_failure_while_saving_leaves_everything_as_it_was(self):
        from django.core.files.storage import default_storage
        list_id = self.make_list(items='A|B')
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        old = self.rows(list_id)[0]
        real_save = default_storage.save
        calls = []

        def flaky_save(name, content, *args, **kwargs):
            calls.append(name)
            if len(calls) == 2:
                raise OSError('disk full')
            return real_save(name, content, *args, **kwargs)

        with mock.patch('lista.views.default_storage.save', side_effect=flaky_save):
            r = self.sync(self.owner, list_id, keep=[],
                          new=[self.new_picture(0, 'JPEG'), self.new_picture(1)])
        self.assertEqual(r.status_code, 500)
        self.assertIn('error', r.json())
        # The old picture and its record are untouched, and the first new file was cleaned up.
        self.assertEqual({i: p.id for i, p in self.rows(list_id).items()}, {0: old.id})
        self.assertTrue(self.file_exists(old))
        self.assertFalse(default_storage.exists(calls[0]))

    def test_only_people_who_can_edit_the_list_can_save_pictures(self):
        list_id = self.make_list()
        self.assertEqual(self.sync(self.anon, list_id, new=[self.new_picture(0)]).status_code, 401)
        self.assertEqual(self.sync(self.stranger, list_id, new=[self.new_picture(0)]).status_code, 403)
        self.share(list_id, self.viewer_data, 'read_only')
        self.assertEqual(self.sync(self.viewer, list_id, new=[self.new_picture(0)]).status_code, 403)
        self.assertEqual(self.rows(list_id), {})
        self.share(list_id, self.editor_data, 'full_access')
        self.assertEqual(self.sync(self.editor, list_id, new=[self.new_picture(0)]).status_code, 200)

    def test_unknown_list_and_bad_requests_give_clear_errors(self):
        self.assertEqual(self.sync(self.owner, 99999).status_code, 404)
        list_id = self.make_list()
        r = self.owner.post('/listitemimages/sync_images/', {
            'list_item_id': list_id, 'keep': 'not json'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        r = self.owner.post('/listitemimages/sync_images/', {}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_saving_with_no_changes_keeps_everything(self):
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        row = self.rows(list_id)[0]
        r = self.sync(self.owner, list_id, keep=[{'id': row.id, 'index': 0}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.rows(list_id)[0].id, row.id)
        self.assertTrue(self.file_exists(row))

    def test_the_original_picture_endpoints_still_work_for_the_current_app(self):
        list_id = self.make_list()
        payload = json.dumps({'uri': PNG_B64, 'fileName': 'old', 'mimeType': 'image/png', 'index': 0})
        r = self.owner.post('/listitemimages/upload_images/',
                            {'list_item': list_id, 'images': [payload]}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(list(self.rows(list_id)), [0])


class PictureFileCleanupTests(PictureSavingBase):
    def test_deleting_a_list_for_good_removes_its_picture_files(self):
        from lista.models import ListItem
        from django.core.files.storage import default_storage
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        path = self.rows(list_id)[0].image.name
        self.assertTrue(default_storage.exists(path))
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete(f'/listitem/{list_id}/')
        self.assertFalse(ListItem.objects.filter(id=list_id).exists())
        self.assertFalse(default_storage.exists(path))

    def test_deleting_a_picture_record_removes_its_file(self):
        from django.core.files.storage import default_storage
        list_id = self.make_list()
        self.sync(self.owner, list_id, new=[self.new_picture(0)])
        image = self.rows(list_id)[0]
        path = image.image.name
        with self.captureOnCommitCallbacks(execute=True):
            r = self.owner.delete(f'/listitemimages/{image.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(default_storage.exists(path))

    def test_a_record_with_the_default_placeholder_does_not_break_deleting(self):
        from lista.models import ListItemImage
        list_id = self.make_list()
        ListItemImage.objects.create(list_item_id=list_id, index=0)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.owner.delete(f'/listitem/{list_id}/')
        self.assertEqual(r.status_code, 204)
