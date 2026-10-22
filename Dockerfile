FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends antiword tesseract-ocr tesseract-ocr-ces tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=10000
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 90 app:app
