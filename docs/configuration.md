[← Back to the README](../Readme.md)

# Configuration

Settings come from environment variables. Locally they live in `myproj/.env` (**git-ignored**); on a host, set the same names in its 
environment. `.env.example` lists them all.

| Variable | Required | Purpose |
|----------|----------|---------|
| `SECRET_KEY` | **Yes** | Django's secret key. Use a long random string, different on every server. The server refuses to start without it |
| `BREVO_API_KEY` | For emails | Brevo API key used to send password-reset emails |
| `DEBUG` | No (default `False`) | `True` only on your own computer |
| `ALLOWED_HOSTS` | On a server | Comma-separated host names. Live: `coral8.pythonanywhere.com` (add `localhost,127.0.0.1` for local use) |
| `CORS_ALLOWED_ORIGINS` | On a server | Websites allowed to call the API. Live: `https://listaa2.netlify.app` (add `http://localhost:8081` for local use) |
| `FRONTEND_URL` | On a server | Website address used to build the link in reset emails. Live: `https://listaa2.netlify.app` |
| `DEFAULT_FROM_EMAIL` | No | Sender address; it must be verified in Brevo (default `listaassistance@gmail.com`) |
| `EMAIL_SENDER_NAME` | No | Name shown next to the sender address (default `Lista`) |

> **Heads-up:** if `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` or `FRONTEND_URL` are not set, the code falls back to the addresses of Lista's first version (a Render server and `lista-project.netlify.app`). Always set all three on a real server.

Other fixed settings: access token **25 minutes**, refresh token **90 days**, request size limit **10 MB** (`DATA_UPLOAD_MAX_MEMORY_SIZE`).

Generate a secret key:  
```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```
