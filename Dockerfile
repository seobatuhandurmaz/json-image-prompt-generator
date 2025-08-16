FROM python:3.11-slim
WORKDIR /app

# Bağımlılıklar
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama
COPY backend/app ./app

EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
