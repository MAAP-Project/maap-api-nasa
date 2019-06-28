FROM python

ARG SSH_PRIVATE_KEY

RUN apt-get update
RUN apt-get install -y git python3-pip python3-venv apache2 vim
COPY . /maap-api-nasa/
RUN python3 -m venv maap-api-nasa && . maap-api-nasa/bin/activate
WORKDIR /maap-api-nasa
RUN pip3 install -r requirements.txt
COPY api/settings.py api/settings.py

CMD FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
