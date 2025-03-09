FROM python:3.11-slim

COPY app app/
COPY requirements.txt requirements.txt 
COPY config.py config.py
COPY entrypoint.sh entrypoint.sh
COPY dbwe-app.py dbwe-app.py

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip
RUN pip install -r requirements.txt
RUN chmod a+x ./entrypoint.sh

EXPOSE 5000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:5000", "dbwe-app:app"]
