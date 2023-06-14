FROM python:3-alpine
WORKDIR /app
RUN pip install --no-cache-dir uvicorn
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "--host", "0.0.0.0", "main:app"]
