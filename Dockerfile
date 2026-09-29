FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN adduser --system --group novabank \
    && mkdir -p /app/staticfiles \
    && chown -R novabank:novabank /app
USER novabank

EXPOSE 8000

# CMD (not ENTRYPOINT) so compose services can override with e.g. celery.
CMD ["./entrypoint.sh"]
