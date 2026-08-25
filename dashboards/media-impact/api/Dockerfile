# Utilizar una imagen base oficial de Python ligera
FROM python:3.11-slim

# Evitar que Python escriba archivos .pyc y asegurar que los logs se emitan en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Establecer el directorio de trabajo en el contenedor
WORKDIR /app

# Instalar dependencias del sistema necesarias para compilar ciertos paquetes si hiciera falta
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copiar el archivo de requerimientos e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código del backend al contenedor
COPY . .

# Exponer el puerto por defecto de Cloud Run (8080)
EXPOSE 8080

# Iniciar el servidor FastAPI usando uvicorn a través de main.py
CMD ["python", "main.py"]
