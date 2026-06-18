# ============================================================
# InkSight → 单个字符 SVG 转换器
# 目标平台：共绩算力 (suanli.cn) Job批处理 · 抢占式实例
# Base: NVIDIA CUDA 12.2 + cuDNN 8 (RTX 4090 兼容)
# ============================================================
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

LABEL description="InkSight - handwriting photo to per-character SVG converter"
LABEL maintainer="wangduoduo2026"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TF_CPP_MIN_LOG_LEVEL=2

# ============================================================
# 1. 系统依赖
# ============================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    python3.11-venv \
    tesseract-ocr \
    libgl1-mesa-glx \
    libglib2.0-0 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# python -> python3.11
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# ============================================================
# 2. Python 工具链
# ============================================================
RUN python -m pip install --upgrade pip uv --quiet

# ============================================================
# 3. 项目依赖
# ============================================================
WORKDIR /app

# 先复制依赖文件（利用 Docker 层缓存）
COPY pyproject.toml uv.lock ./
COPY utils/ ./utils/

# 创建虚拟环境并安装所有依赖
RUN uv venv --python python3.11 && \
    . .venv/bin/activate && \
    uv sync

# 额外安装 OpenCV（字符轮廓分割用，无头版本）
RUN . .venv/bin/activate && \
    pip install opencv-python-headless --quiet

# 压缩工具（打包 SVG 用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    zip \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# 4. 预下载 InkSight 模型（构建时缓存，运行时零等待）
# ============================================================
RUN . .venv/bin/activate && python -c "import os; os.environ['TF_CPP_MIN_LOG_LEVEL']='3'; from huggingface_hub import from_pretrained_keras; print('[build] Downloading InkSight Small-p model...'); model = from_pretrained_keras('Derendering/InkSight-Small-p'); print('[build] Model cached ✓')"

# ============================================================
# 5. 应用代码 & 输入图片
# ============================================================
COPY process.py entrypoint.sh .
COPY inksight.jpg .

RUN mkdir -p /output && chmod +x entrypoint.sh

# ============================================================
# 6. 端口说明（HTTP 下载用，是否映射取决于算力平台）
# ============================================================
EXPOSE 8080

# ============================================================
# 7. 启动
# ============================================================
ENTRYPOINT ["/bin/bash", "entrypoint.sh"]
