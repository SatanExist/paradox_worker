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
# Игнорируем вшитый системный пакет blinker, чтобы pip не крашился при его обновлении
RUN pip install --no-cache-dir --ignore-installed blinker
# Устанавливаем всё остальное
RUN pip install --no-cache-dir imageio imageio-ffmpeg easydict opencv-python-headless scipy rembg onnxruntime trimesh xatlas pyvista pymeshfix igraph pydantic gradio_litmodel3d xformers==0.0.20 open3d numpy==1.26.4 transformers==4.40.2 tables
RUN pip install --no-cache-dir git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

# 6. Копируем локальный TRELLIS в контейнер
COPY TRELLIS /app/TRELLIS

# 6.5. FlexiCubes: TRELLIS needs MaxtirError fork (relative imports + vertex attrs).
# Do NOT use nv-tlabs/FlexiCubes — its `from tables import *` breaks as a submodule (dmc_table NameError).
RUN rm -rf /app/TRELLIS/trellis/representations/mesh/flexicubes && \
    git clone https://github.com/MaxtirError/FlexiCubes.git /app/TRELLIS/trellis/representations/mesh/flexicubes && \
    cd /app/TRELLIS/trellis/representations/mesh/flexicubes && \
    git checkout f97beb0dd3c6c68f3ab5696b6dcaf9af69f0514e && \
    touch /app/TRELLIS/trellis/representations/mesh/flexicubes/__init__.py

# 6.6. Kaolin required by FlexiCubes (check_tensor, mesh extraction)
RUN pip install --no-cache-dir kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.0.1_cu118.html

# 6.7. nvdiffrast required by MeshRenderer / render_glb export
RUN git clone https://github.com/NVlabs/nvdiffrast.git /tmp/nvdiffrast && \
    pip install --no-cache-dir /tmp/nvdiffrast && \
    rm -rf /tmp/nvdiffrast

# 7. МАГИЯ: Указываем Python, где искать исходники TRELLIS
ENV PYTHONPATH="/app/TRELLIS"

# 8. Копируем наш код воркера
COPY worker.py /app/worker.py

# 9. Запуск
CMD [ "python", "-u", "/app/worker.py" ]