# Gunakan image Python sebagai base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Salin file requirements.txt ke dalam container
COPY requirements.txt .

# Instal dependensi
RUN pip install --no-cache-dir -r requirements.txt

# Salin semua file aplikasi ke dalam container
COPY . .

# Set variabel lingkungan untuk port
ENV PORT 5000

# Jalankan aplikasi
CMD ["python", "wp.py"]
