FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose default port; hosting platforms typically inject $PORT.
ENV PORT=8000
EXPOSE 8000

CMD gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT
