FROM amancevice/pandas:2.1.4-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi uvicorn plotly pydantic python-multipart
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
