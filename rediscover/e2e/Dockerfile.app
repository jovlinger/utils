FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rediscover/ ./rediscover/
COPY e2e/app.py ./app.py
CMD ["python", "app.py"]
