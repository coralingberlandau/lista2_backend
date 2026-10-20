[← Back to the README](../Readme.md)

# Architecture and Technology

![Lista 2 architecture](architecture.svg)

| Part | Where it runs | Role |
|------|---------------|------|
| **Frontend** (separate repository) | Netlify (`listaa2.netlify.app`) | React Native + Expo web app: every screen, session renewal and error messages |
| **Backend API** (this repository) | PythonAnywhere (`coral8.pythonanywhere.com`) | Django REST Framework: accounts, lists, sharing and permissions, images, backgrounds, password reset |
| **Database and files** | PythonAnywhere persistent disk | SQLite database and uploaded images |
| **Email** | Brevo web API | Sends the password-reset email |
| **AI suggestions** | Netlify function + Google Gemini | Lives in the frontend project; this API is not involved |

**How a request flows**
1. The app sends an HTTPS request with `Authorization: Bearer <access token>`.  
2. Django REST Framework checks the token: **every endpoint requires a login unless it is explicitly public**.  
3. The view checks **who may do what** on that list (owner, Full Access, Read-Only), then reads or writes the database.  
4. The request is logged with tokens, cookies and passwords redacted.  
5. When the short-lived access token expires, the app swaps its refresh token at `/token/refresh/` and repeats the request.

**Why this hosting?** The database is a single SQLite file, so the server needs a disk that persists between restarts; 
PythonAnywhere provides one on its free plan. The frontend is a static site plus a serverless function, which fits Netlify. 
Each part can be redeployed independently.

## Technology

| Domain | Technology |
|--------|------------|
| Frontend | React Native + Expo (web), hosted on **Netlify** |
| Backend | **Django 5.2 LTS** and Django REST Framework |
| Authentication | JWT (access + rotating refresh tokens) and Django's password validators |
| Database | SQLite on a persistent disk |
| Hosting (API) | **PythonAnywhere** |
| Email | **Brevo** web API |
| AI ideas | Google Gemini, called by a Netlify function in the frontend project |
| Quality | 73 automated tests, `pip-audit`, Pylint and autopep8 (`requirements-dev.txt`) |
