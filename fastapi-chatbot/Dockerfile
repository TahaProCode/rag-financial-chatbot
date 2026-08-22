FROM python:3.13-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Pehle CPU-only PyTorch setup karein taake 3GB NVIDIA CUDA packages download na hon
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. Dependencies pehle install karein
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Model save script pehle copy karke chalaayein (HTML/JS badalne par model dobara save nahi hoga)
COPY app/save_model.py app/save_model.py
RUN python app/save_model.py

# 4. Baaki saara app code aakhir mein copy karein
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]