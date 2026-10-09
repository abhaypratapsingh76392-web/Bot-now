FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# ⚡ गुनिकॉर्न को 1 वर्कर और 1 थ्रेड के साथ चलाएं (सर्वर क्रैश से बचने के लिए)
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 300 app:app