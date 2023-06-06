FROM python:3-alpine
WORKDIR /app
RUN pip install --no-cache-dir hypercorn
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["hypercorn", "--bind", "0.0.0.0", "main:app"]
