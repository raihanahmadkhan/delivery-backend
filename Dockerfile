FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
COPY requirements-bootstrap.txt .
RUN python -m pip install --no-cache-dir -r requirements-bootstrap.txt && python -m pip install --no-cache-dir -r requirements.txt

COPY main.py config.py ./
COPY routelab ./routelab
RUN useradd --create-home --uid 10001 routelab && mkdir -p /app/data && chown routelab:routelab /app/data
USER routelab
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ROUTELAB_DB=/app/data/routelab.sqlite3

EXPOSE 8000

# Single API process; the Compose worker owns CPU execution.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
