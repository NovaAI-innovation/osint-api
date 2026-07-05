FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for OSINT tools (example)
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run the worker
CMD ["python", "main.py"]