FROM python:3.7

WORKDIR /usr/src/app

COPY requirements.txt /usr/src/app
RUN pip install --upgrade -r ./requirements.txt

COPY . /usr/src/app

CMD ["python", "cli.py"]
