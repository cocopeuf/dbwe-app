#!/bin/bash
# Initialize
if [ ! -d "migrations" ]; then
    echo "Initializing database migrations..."
    flask db init
fi
# Migrate and upgrade the database if necessary
while true; do
    flask db upgrade
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo "Deploy command failed, retrying in 5 secs..."
    sleep 5
done

# Starte Gunicorn als WSGI-Server
exec gunicorn -w 2 -b :5000 --access-logfile - --error-logfile - dbwe-app:app
