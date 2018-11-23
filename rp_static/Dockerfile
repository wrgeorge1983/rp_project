FROM python:3.6


RUN pip install --upgrade pipenv


WORKDIR /usr/src/app

COPY . .
RUN pipenv install

#COPY . /usr/src/app

CMD ["pipenv", "run", "rp_static"]
