FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir requests pandas psycopg2-binary python-dotenv
COPY ingest_air.py .
CMD ["python", "ingest_air.py"]
