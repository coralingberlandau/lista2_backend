[← Back to the README](../Readme.md)

# Testing, Code Quality and Logging

The project has **73 automated tests** that call the API exactly as the app does (same URLs, bodies and headers):  

```bash
python manage.py test lista
```

They cover: registration and its errors, password rules, login and refresh-token rotation, protected endpoints rejecting anonymous users, 
creating, updating and deactivating lists, sharing with Read-Only and Full Access, strangers and view-only members being refused, 
images (upload, public listing, download, permissions), backgrounds, profiles, password reset (missing, wrong, reused and expired tokens, 
failed email, missing key) and the guarantee that tokens never reach the log file.

Other checks used before every release: `python manage.py check --deploy`, `python manage.py makemigrations --check --dry-run` and `pip-audit -r requirements.txt`.

## Code quality and logging

- **Pylint Analysis:**  
  Code is checked with Pylint to ensure clean and readable syntax.  
  First, install the development tools (**Pylint** and **autopep8**) with the following command:  
  ```bash
  pip install -r requirements-dev.txt
  ```
  Once installed, you can run the following command to analyze the code:  
  ```bash
  pylint <file_name>.py
  ```
  To include project-specific settings, and when you have a `pylintrc` configuration file, run the following command:  
  ```bash
  pylint --rcfile=.pylintrc lista/
  ```

- **Logging:**  
  Logs are stored in `logs/application.log` (created automatically, git-ignored) and used for debugging and performance analysis.  
  Sensitive values are removed before anything is written: `Authorization` headers, cookies, and any token in a result appear as `[REDACTED]`.  
  Example log entry (INFO level):  
  ```json
  {
    "timestamp": "2024-11-19T12:34:56",
    "level": "INFO",
    "message": "New user registered: user1"
  }
  ```

## Development process

1. **Planning and Design**  
   - Market research, wireframes, and user interface design.  

2. **Frontend Development**  
   - Built with React Native and Expo.  

3. **Backend Development**  
   - Developed using Django for API, authentication, and security.  

4. **Integration**  
   - Seamless data exchange using Axios.  

5. **Quality Assurance (QA)**  
   - Manual and automated feature testing; in Lista 2, 73 automated tests plus dependency and deployment checks.  

6. **Release and Feedback**  
   - Initial launch followed by user feedback for continuous improvement.  

7. **Security review and hardening**  
   - A full review of every endpoint, with each fix verified by tests, current dependency versions, a transactional email provider and a persistent hosting setup.
