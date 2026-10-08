import json
import logging
import os
import platform
import re
import time
import traceback
from functools import wraps
from logging.handlers import RotatingFileHandler

# Absolute path, so the log goes to <project>/logs/ no matter which folder the server
# was started from (the same file Django's LOGGING setting writes to).
LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "application.log")

"""
Logging utility module.

This module provides functionality for logging various events within the application.
It includes custom log formatting (JSONFormatter), setting up a rotating file-based logger,
and logging different types of events such as API calls, deletions, and function executions.
The logs contain important metadata including execution time, user and object information, 
IP address, headers, and dynamic information.

Functions:
- setup_logger: Configures the logger with a rotating file handler.
- log_api_call: Logs information about API calls, including URL, method, 
  status code, and response time.
- log_deletion: Logs information about deletions (user, object, and type).
- log: A decorator for logging function calls, including execution time, arguments, and errors.

Dependencies:
- json: For serializing log records to JSON.
- logging: For setting up and managing loggers.
- os: For handling file system operations (e.g., creating directories).
- platform: For collecting system information (e.g., OS, Python version).
- time: For tracking execution time.
- traceback: For extracting stack traces when errors occur.
- functools: For creating function decorators.
- logging.handlers: For handling rotating log files.
"""

class JSONFormatter(logging.Formatter):
    """
    Custom logging formatter that converts log records into JSON format.
    This formatter includes information such as time, log level, message, 
    function, filename, line number, system information, and dynamic data.
    """

    def format(self, record):
        """
        Formats the log record into JSON format.
        
        Args:
            record (logging.LogRecord): The log record to be formatted.

        Returns:
            str: A JSON formatted log record.
        """
        log_record = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "function": record.funcName,
            "filename": record.filename,
            "line": record.lineno,
            "host": platform.node(),
            "system": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        dynamic_info = getattr(record, 'dynamic_info', None)
        if dynamic_info and isinstance(dynamic_info, dict):
            log_record.update(dynamic_info)
        else:
            log_record["dynamic_info"] = "No dynamic info provided"

        return json.dumps(log_record)


# ------------------- Logger Setup -------------------

def setup_logger(log_file, level=logging.DEBUG):
    """
    Sets up the logger to output to a rotating file handler, with a custom JSON formatter.
    
    Args:
        log_file (str): The path of the log file.
        level (int): The logging level. Default is logging.DEBUG.

    Returns:
        logging.Logger: The configured logger instance.
    """
    logger = logging.getLogger("application_logger")
    if not logger.hasHandlers():
        logger.setLevel(level)
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger


# ------------------- API Call Logging -------------------

def log_api_call(url, method, status_code, response_time, payload=None):
    """
    Logs an API call event.
    
    Args:
        url (str): The URL of the API call.
        method (str): The HTTP method used (e.g., GET, POST).
        status_code (int): The HTTP status code returned.
        response_time (float): The time it took for the request to complete.
        payload (dict, optional): The request payload.
    """
    logger = setup_logger(LOG_FILE)
    logger.info({
        "event": "api_call",
        "url": url,
        "method": method,
        "status_code": status_code,
        "response_time": f"{response_time:.2f}s",
        "payload": payload,
    })


# ------------------- Deletion Logging -------------------
def log_deletion(user_id, object_id, object_type):
    """
    Logs a deletion event (e.g., a record being deleted).
    
    Args:
        user_id (int): The ID of the user performing the deletion.
        object_id (int): The ID of the object being deleted.
        object_type (str): The type of object being deleted.
    """
    logger = setup_logger(LOG_FILE)
    logger.warning({
        "event": "deletion",
        "user_id": user_id,
        "object_id": object_id,
        "object_type": object_type,
    })


# ------------------- Keeping secrets out of the log -------------------

# Headers that carry credentials. Their values are never written to the log file.
SENSITIVE_HEADERS = {"authorization", "cookie", "x-csrftoken", "proxy-authorization"}

# JSON Web Tokens (access and refresh tokens) look like  xxxxx.yyyyy.zzzzz  and start
# with "eyJ". Any such string in a logged result is replaced.
_JWT_PATTERN = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")


def redact_headers(headers):
    """Return a copy of the request headers with credential values hidden."""
    return {
        name: ("[REDACTED]" if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in dict(headers).items()
    }


def redact_tokens(text):
    """Replace any JWT found in the text, e.g. the result of get_token()."""
    return _JWT_PATTERN.sub("[REDACTED_TOKEN]", text)


# ------------------- Function Call Logging Decorator -------------------

def log(user_id=None, object_id=None):
    """
    Decorator for logging function calls. Logs information about the function call, 
    such as the function name, arguments, user, and request details. 
    Logs both successful executions and errors.

    Args:
        user_id (int, optional): The ID of the user related to the function call.
        object_id (int, optional): The ID of the object related to the function call.

    Returns:
        function: A wrapper function that logs the function execution.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = setup_logger(LOG_FILE)
            function_name = func.__name__
            file_name = os.path.basename(func.__code__.co_filename)
            start_time = time.time()

            request = args[1] if len(args) > 1 else None
            user_info = f"User ID: {user_id}" if user_id else "No User Info"
            object_info = f"Object ID: {object_id}" if object_id else "No Object Info"

            if request and hasattr(request, 'META'):
                ip_address = request.META.get('REMOTE_ADDR', 'Unknown IP')
                method = request.method if hasattr(request, 'method') else 'No Method'
                headers = request.headers if hasattr(request, 'headers') else 'No Headers'
            else:
                ip_address = 'No Request Info'
                method = 'No Method'
                headers = 'No Headers'

            logger.debug({
                "event": "function_call",
                "function": function_name,
                "file": file_name,
                "user_info": user_info,
                "object_info": object_info,
                "ip": ip_address,
                "method": method,
                "headers": redact_headers(headers) if headers != 'No Headers' else "No Headers",
            })

            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time

                dynamic_info = {
                    "extra_info_key": "additional_value",
                    "another_field": "another_value"
                }
                if dynamic_info is None:
                    dynamic_info = {
                        "message": "No additional dynamic information"}

                logger.info({
                    "event": "function_success",
                    "function": function_name,
                    "execution_time": execution_time,
                    "result": redact_tokens(str(result)),
                    "dynamic_info": dynamic_info
                })
                return result

            except Exception as e:
                logger.error({
                    "event": "error",
                    "function": function_name,
                    "error": str(e),
                    "stack_trace": traceback.format_exc(limit=3),
                })
                raise

        return wrapper
    return decorator
