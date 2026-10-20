[← Back to the README](../Readme.md)

# Run It Locally and Deploy

## Run it locally

Follow these steps to run the backend locally (Python 3.10 or newer):  

1. **Clone the repository:**  
   ```bash
   git clone https://github.com/coralingberlandau/lista2_backend.git
   cd lista2_backend
   ```

2. **Create a virtual environment:**  
   - macOS/Linux:  
     ```bash
     python3 -m venv env
     source env/bin/activate
     ```  
   - Windows:  
     ```bash
     python -m venv env
     env\Scripts\activate
     ```
   Once activated, the terminal prompt shows `(env)`. Leave it with `deactivate`.

3. **Install dependencies:**  
   ```bash
   pip install -r requirements.txt
   ```

4. **Create your settings file:** copy `.env.example` to `myproj/.env` and fill it in. For local use at least:  
   ```
   SECRET_KEY=a-long-random-string
   DEBUG=True
   ```
   Add `BREVO_API_KEY=...` if you want to send real reset emails. **Never commit this file** (it is git-ignored).

5. **Create the database:**  
   ```bash
   python manage.py migrate
   ```
   The database file (`db.sqlite3`) is created for you. You can delete it at any time and run `migrate` again to start from scratch.

6. **Start the server:**  
   ```bash
   python manage.py runserver
   ```
   The API is now at `http://localhost:8000`. Point the frontend at it with `EXPO_PUBLIC_API_URL=http://localhost:8000`.

For macOS use `python3` / `pip3`; on Windows use `py`.

## Deploy to PythonAnywhere

The backend is deployed on **PythonAnywhere**; the frontend on Netlify. **Deploy the backend first**, then the frontend.

The live server is `https://coral8.pythonanywhere.com`. To set up your own copy:

1. **Create a PythonAnywhere account** (the free *Beginner* plan is enough). Your username becomes your address, `username.pythonanywhere.com`.  
2. **Get the code:** open a **Bash console** and run  
   ```bash
   git clone https://github.com/coralingberlandau/lista2_backend.git
   cd lista2_backend
   mkvirtualenv lista --python=python3.12   # use a version PythonAnywhere offers (3.10+)
   pip install -r requirements.txt
   ```

3. **Create the settings file** `~/lista2_backend/myproj/.env` (use the Files tab or `nano`) with:  
   ```
   SECRET_KEY=<a NEW long random string, different from your local one>
   DEBUG=False
   ALLOWED_HOSTS=username.pythonanywhere.com
   CORS_ALLOWED_ORIGINS=https://your-site.netlify.app
   FRONTEND_URL=https://your-site.netlify.app
   BREVO_API_KEY=<your Brevo key>
   ```
4. **Create the database and static files:**  
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```
5. **Web tab > Add a new web app > Manual configuration** (same Python version). Set **Source code** and **Working directory** to 
   `/home/username/lista2_backend` and **Virtualenv** to `/home/username/.virtualenvs/lista`.  
6. **WSGI file** (link on the Web tab): replace its contents with  
   ```python
   import os, sys
   path = '/home/username/lista2_backend'
   if path not in sys.path:
       sys.path.append(path)
   os.environ['DJANGO_SETTINGS_MODULE'] = 'myproj.settings'
   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
7. **Static files table** (Web tab): map `/static/` → `/home/username/lista2_backend/staticfiles` and 
   `/images/` → `/home/username/lista2_backend/static/images`.  
8. On the Web tab, switch on **Force HTTPS**, then **Reload** the web app and open `https://username.pythonanywhere.com/login/`: a "Method not allowed" answer means the server is running (that address expects a login request, not a page view).  
9. **Test the email** from a Bash console (replace the address):  
   ```bash
   python manage.py shell
   >>> from django.contrib.auth.models import User
   >>> from lista import views
   >>> u = User.objects.create(username="mailtest", email="you@example.com")
   >>> views.send_password_reset_email(u)   # True means Brevo accepted it
   >>> u.delete()
   ```
10. **Deploy the frontend** (see its README) and then put its address in `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` if you have not already.

### Updating the live server
After new code is pushed to GitHub, in a PythonAnywhere Bash console:
```bash
cd ~/lista2_backend
git pull
workon lista
pip install -r requirements.txt     # only needed when requirements changed
python manage.py migrate            # only needed when the models changed
```
Then press **Reload** on the Web tab. Uploaded pictures and the database are not in Git, so an update never touches them.

**PythonAnywhere free-plan notes:** the web app must be renewed periodically from the Web tab (the page shows the expiry date); CPU time is limited per day; 
outgoing connections go through an allowlist that includes `api.brevo.com`. Back up `db.sqlite3` and `static/images/` from time to time.
