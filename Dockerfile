# Берем за основу мощный образ с Linux, Python 3.10 и драйверами NVIDIA
FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# 1. Системные зависимости (компиляторы для надежности)
RUN apt-get update && apt-get install -y \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. Обновляем базовые инструменты Python
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 3. Базовые библиотеки для воркера
RUN pip install --no-cache-dir runpod Pillow requests

# 4. Специфические ускорители для 3D-сетей (SpConv)
RUN pip install --no-cache-dir ninja spconv-cu118

# 5. БЕЗОПАСНЫЙ ПУТЬ: Копируем локальный TRELLIS в контейнер
COPY TRELLIS /app/TRELLIS

# 6. МАГИЯ: Указываем Python, где искать исходники TRELLIS (вместо установки через pip)
ENV PYTHONPATH="/app/TRELLIS"

# 7. Устанавливаем зависимости самой нейросети
# Робот проверит: если файл требований есть - он скачает все нужные библиотеки
RUN if [ -f "/app/TRELLIS/requirements.txt" ]; then pip install --no-cache-dir -r /app/TRELLIS/requirements.txt; fi

# 8. Копируем наш код воркера внутрь контейнера
COPY worker.py /app/worker.py

# 9. Указываем команду для запуска
CMD [ "python", "-u", "/app/worker.py" ]