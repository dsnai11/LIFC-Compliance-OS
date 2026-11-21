# Production image for Railway (build context = repo root). Server only; the React build is committed in server/static/app.
FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/app.py .
COPY server/static ./static
ENV CCT_DATA=/data PYTHONUNBUFFERED=1
EXPOSE 8080
# Single worker on purpose: state is serialised through one SQLite connection and an in-process lock.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]
