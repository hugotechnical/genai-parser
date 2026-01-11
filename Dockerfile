FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
# TESSDATA_PREFIX nên trỏ thẳng đến thư mục chứa các file .traineddata
ENV TESSDATA_PREFIX=/usr/local/share/tessdata/

WORKDIR /app

# 1. Install system dependencies (Tối ưu hóa dung lượng)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    wget \
    fonts-dejavu \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Tesseract language data (Gộp layer và phân quyền)
RUN mkdir -p $TESSDATA_PREFIX \
    && wget -q -O ${TESSDATA_PREFIX}vie.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/vie.traineddata \
    && wget -q -O ${TESSDATA_PREFIX}eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata \
    && chmod 644 ${TESSDATA_PREFIX}*.traineddata

# 3. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy application source
COPY app ./app

# 5. Create required runtime directories & Permissions
RUN mkdir -p /app/logs /tmp/lo_profile \
    && chmod -R 777 /tmp/lo_profile /app/logs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]