"""
Gunicorn config for Railway, Render, and local Docker.

Railway sets PORT — the app must bind to it (not a fixed 8000) or the proxy returns 502.
"""
import os

# Railway / Render / Fly inject PORT
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "1"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))

accesslog = "-"
errorlog = "-"
capture_output = True

# Mitigate slow memory growth on long-running workers
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))
