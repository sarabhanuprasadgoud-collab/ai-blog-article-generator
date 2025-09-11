#!/bin/sh
# entrypoint.sh

# Run database migrations
echo "Runing migrations..."
python manage.py migrate --noinput

# Collect static files(Cloudinary)
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Nginx
echo "Starting Nginx..."
service nginx start 

# Start Gunicorn
echo "Starting Gunicorn..."
gunicorn ai-bog-article-generator.wsgi:application -- bind 0.0.0.0:$PORT --workers 3
