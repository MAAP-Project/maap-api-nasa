FROM python

ARG SSH_PRIVATE_KEY

RUN apt-get update
RUN apt-get install -y git python3-pip python3-venv apache2 vim
RUN mkdir /root/.ssh/
RUN echo "${SSH_PRIVATE_KEY}" > /root/.ssh/id_rsa
RUN chmod 700 /root/.ssh/id_rsa
RUN touch /root/.ssh/known_hosts
RUN ssh-keyscan github.com >> /root/.ssh/known_hosts
# TODO(update with repo)
# git clone -b abarciauskas-bgse_tiling-endpoint git@github.com:developmentseed/maap-api-nasa.git
COPY . /maap-api-nasa/
COPY maap-py /maap-api-nasa/maap-py
RUN cd /maap-api-nasa/maap-py && python setup.py install
RUN python3 -m venv maap-api-nasa && . maap-api-nasa/bin/activate
WORKDIR /maap-api-nasa
RUN pip3 install -r requirements.txt
COPY settings.py api/settings.py

CMD FLASK_APP=api/maapapp.py flask run --host=0.0.0.0
