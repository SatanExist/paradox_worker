# Берем за основу мощный образ с Linux, Python 3.10 и драйверами NVIDIA
FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# 1. Системные пакеты
RUN apt-get update && apt-get install -y \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. Обновляем инструменты установки
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 3. Базовые библиотеки для нашего скрипта
RUN pip install --no-cache-dir runpod Pillow requests

# 4. Специфические ускорители для 3D-сетей (строго под нашу CUDA 11.8)
RUN pip install --no-cache-dir ninja spconv-cu118

# 5. ХИРУРГИЧЕСКАЯ УСТАНОВКА ЗАВИСИМОСТЕЙ TRELLIS
# (Игнорируем их requirements.txt, ставим только то, что безопасно)
RUN pip install --no-cache-dir imageio imageio-ffmpeg easydict opencv-python-headless scipy rembg onnxruntime trimesh xatlas pyvista pymeshfix igraph transformers pydantic gradio_litmodel3d xformers==0.0.20
RUN pip install --no-cache-dir git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

# 6. Копируем локальный TRELLIS в контейнер
COPY TRELLIS /app/TRELLIS

# 7. МАГИЯ: Указываем Python, где искать исходники TRELLIS
ENV PYTHONPATH="/app/TRELLIS"

# 8. Копируем наш код воркера
COPY worker.py /app/worker.py

# 9. Запуск
CMD [ "python", "-u", "/app/worker.py" ]