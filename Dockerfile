# Use the official Python image from the Docker Hub
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory
WORKDIR /app
COPY requirements.txt /app/

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY app app
COPY migrations migrations
COPY dbwe-app.py config.py boot.sh ./
RUN chmod a+x boot.sh

ENV FLASK_APP dbwe-app.py

# Expose the port the app runs on
EXPOSE 5000
# Run the application using the start script
CMD ["./boot.sh"]