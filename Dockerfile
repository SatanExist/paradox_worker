# Берем за основу мощный образ с Linux, Python 3.10 и драйверами NVIDIA
FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# 1. Устанавливаем системные пакеты (нужны для работы с графикой)
RUN apt-get update && apt-get install -y git libgl1-mesa-glx libglib2.0-0

# 2. Устанавливаем базовые библиотеки для нашего скрипта
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir runpod Pillow requests

# 3. Устанавливаем специфические ускорители для 3D-сетей (SpConv)
RUN pip install --no-cache-dir ninja spconv-cu118

# 4. Устанавливаем сам TRELLIS напрямую из репозитория Microsoft
RUN pip install --no-cache-dir git+https://github.com/microsoft/TRELLIS.git

# 5. Копируем наш код воркера внутрь контейнера
COPY worker.py /app/worker.py

# 6. Указываем команду для запуска
CMD [ "python", "-u", "/app/worker.py" ]