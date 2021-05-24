FROM python:3.9-alpine

RUN pip install websockets flask asyncio-dgram

RUN mkdir /app
WORKDIR /app

COPY . /app/

CMD ["python", "main.py"]
