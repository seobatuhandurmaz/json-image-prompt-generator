FROM python:3.11-slim
WORKDIR /app

# Bağımlılıklar
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama
COPY backend/app ./app

# (opsiyonel) healthcheck için port
EXPOSE 8000

# Çalıştırma
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
