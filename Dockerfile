FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Run uvicorn with production settings
# Use --host 0.0.0.0 so Docker port mapping works
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
