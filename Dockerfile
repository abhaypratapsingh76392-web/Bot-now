# Playwright की ऑफिशियल Python इमेज (सारे ब्राउज़र डिपेंडेंसी पहले से हैं)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# डिपेंडेंसी इंस्टॉल करें
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# बाकी कोड कॉपी करें
COPY . .

# Render द्वारा दिए गए PORT का उपयोग करें
ENV PORT=8000
EXPOSE 8000

# Gunicorn के साथ ऐप रन करें
CMD gunicorn --bind 0.0.0.0:$PORT app:app
