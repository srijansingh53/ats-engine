"""Production gunicorn settings. Override any of them with env vars."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "150"))  # Claude calls can take ~30-90 s
graceful_timeout = 30
keepalive = 5
max_requests = 1000  # recycle workers to cap memory growth
max_requests_jitter = 100
forwarded_allow_ips = "*"
accesslog = None  # the app logs each API request with a request id
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
