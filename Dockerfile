#=====================================================
# Stage : Build Dependencies (Use Python slim image)
#=====================================================
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies (needed for psycopg2, Pillow, ffmpg)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements-linux.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-linux.txt

#=====================================================
# Stage : Runtime container (Use Python slim image)
#=====================================================
FROM python:3.11-slim 

# Set working directory
WORKDIR /app

# Install only runtime packages(lighter than full build)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy project files
COPY . .

# Copy Nginx config
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Set environment variables
ENV PYTHONUNBUFFERED=1

#Collect static (uploads to clodinaryif configured)
RUN python manage.py collectstatic --noinput || true

# Expose Render port
EXPOSE 10000

# Run Django server
# CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Start Nginx + Gunicorn (2 workers safe for Render free tier)
CMD service nginx start && \
    gunicorn ai-blog-article-generator:wsgi:application \
    --bind 0.0.0.0:10000 \
    --workers=2 --threads=2 --timeout=120


