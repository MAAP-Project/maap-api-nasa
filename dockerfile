FROM python

WORKDIR /maap-api-nasa
COPY . .
COPY api/settings.py api/settings.py
RUN pip3 install -r requirements.txt
CMD FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
