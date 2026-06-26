FROM python:3.10-slim

# Ağır kütüphanelerin (Pandas vb.) hızlı derlenmesi için sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Bağımlılıkları kuruyoruz (Eğer requirements.txt yoksa veya JSON ise direkt elle kurduruyoruz garanti olsun diye)
RUN pip install --no-cache-dir fastapi uvicorn pandas numpy plotly pydantic python-multipart

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
