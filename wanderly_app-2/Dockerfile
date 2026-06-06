FROM python:3.12-slim

# Keep Python lean and unbuffered for predictable container logs.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static assets at build time (no-op-safe if none).
RUN python manage.py collectstatic --noinput || true

EXPOSE 8000

# Run migrations, then serve via gunicorn. In production, DJANGO_DEBUG=0
# and the Postgres env vars should be supplied (see docker-compose.yml).
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn wanderly.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
