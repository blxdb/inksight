# ============================================================
# InkSight → 单个字符 SVG 转换器
# slim 基础 + pip 清华镜像 + HF 国内镜像
# ============================================================
FROM docker.m.daocloud.io/library/python:3.11-slim

LABEL description="InkSight - handwriting photo to per-character SVG converter"
LABEL maintainer="wangduoduo2026"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TF_CPP_MIN_LOG_LEVEL=2
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# ---- 系统依赖 ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    tesseract-ocr \
    libgl1-mesa-glx \
    libglib2.0-0 \
    build-essential \
    zip \
    && rm -rf /var/lib/apt/lists/*

# ---- 安装 uv（PyTorch/TF 项目标准工具） ----
RUN pip install --no-cache-dir uv

# ---- 复制依赖文件 ----
COPY pyproject.toml uv.lock ./
COPY utils/ ./utils/

# ---- 安装项目依赖（虚拟环境） ----
RUN uv venv && \
    . .venv/bin/activate && \
    uv sync --no-cache

# ---- 额外依赖（OpenCV 无头版 + TensorFlow Text） ----
RUN . .venv/bin/activate && \
    pip install --no-cache-dir opencv-python-headless tensorflow-text

# ---- 预下载 InkSight 模型（构建时缓存） ----
RUN . .venv/bin/activate && python -c "import os; os.environ['TF_CPP_MIN_LOG_LEVEL']='3'; import tensorflow_text; from huggingface_hub import from_pretrained_keras; print('[build] Downloading InkSight Small-p model...'); model = from_pretrained_keras('Derendering/InkSight-Small-p'); print('[build] Model cached ✓')"

# ---- 应用代码 & 输入图片 ----
COPY process.py entrypoint.sh .
COPY inksight.jpg .

RUN mkdir -p /output && chmod +x entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/bin/bash", "entrypoint.sh"]
