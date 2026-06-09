FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# adb 用来与宿主机上的 adb server 通信（USB 设备由宿主负责，容器只发指令）
RUN apt-get update \
    && apt-get install -y --no-install-recommends adb curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8099

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
