# ============================================================
# InkSight — 业务代码层（构建极快）
# 依赖 Harbor 上的 inksight-base 镜像
# ============================================================
FROM harborpush.suanleme.cn/wangduoduo2026/inksight-base:latest

LABEL description="InkSight - handwriting photo to per-character SVG converter"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TF_CPP_MIN_LOG_LEVEL=2
ENV HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# ---- 应用代码 & 输入图片 ----
COPY process.py entrypoint.sh .
COPY inksight.jpg .

RUN mkdir -p /output && chmod +x entrypoint.sh

VOLUME ["/output"]
EXPOSE 8080
ENTRYPOINT ["/bin/bash", "entrypoint.sh"]
