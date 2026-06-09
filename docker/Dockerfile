# TwLandPrice 實價登錄擷取程式的執行環境。
FROM python:3.12-slim

WORKDIR /app

# 先安裝相依套件，善用 Docker layer 快取。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案程式碼。
COPY . .

# 預設執行單元測試。
CMD ["pytest"]
