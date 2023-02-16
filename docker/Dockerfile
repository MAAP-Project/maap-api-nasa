FROM python:3.7

RUN apt-get update && apt-get install -y lsb-release && apt-get clean all
RUN echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
RUN apt-get update && apt-get install -y postgresql postgresql-contrib git

WORKDIR /maap-api-nasa
COPY . .
COPY api/settings.py api/settings.py
RUN pip3 install -r requirements.txt
