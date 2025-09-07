# Use Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements-linux.txt .

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-linux.txt

# Copy project files
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Run Django server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
