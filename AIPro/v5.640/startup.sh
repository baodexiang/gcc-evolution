#!/bin/bash

# Install dependencies if virtual environment doesn't exist
if [ ! -d "antenv" ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Start gunicorn
gunicorn --bind=0.0.0.0:8000 --timeout 120 app:app
