FROM python:3.13-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Pehle CPU-only PyTorch setup karein
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. Dependencies install karein
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Code aur Local Model copy karein
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]