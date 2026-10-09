FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# ⚡ Gunicorn टाइमआउट 180 सेकंड कर दिया है
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 180 app:app
