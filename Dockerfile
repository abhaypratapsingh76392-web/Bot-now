FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# ⚡ Uvicorn को 1 Worker के साथ चलाएं ताकि मेमोरी क्रैश न हो
CMD exec uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 60