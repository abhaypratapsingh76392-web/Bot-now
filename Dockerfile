FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# ⚡ गुनिकॉर्न को 1 वर्कर के साथ चलाएं (मल्टी-थ्रेडिंग से बचने के लिए, ताकि क्रैश न हो)
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app
