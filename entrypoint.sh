#!/bin/bash
# ============================================================
# InkSight 处理器 — 入口脚本
# 1. 运行 process.py 生成 SVG
# 2. 打包 zip
# 3. 启动 HTTP 服务供下载
# ============================================================
set -e

cd /app

echo "=========================================="
echo "  InkSight 手写字符 -> SVG 转换器"
echo "=========================================="

# 1. 处理图片
.venv/bin/python process.py "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "失败，退出码 $EXIT_CODE"
    exit $EXIT_CODE
fi

# 2. 打包所有 SVG 到 zip
echo ""
echo "打包 SVG 文件..."
SVG_COUNT=$(ls -1 /output/*.svg 2>/dev/null | wc -l)
cd /output && zip -q -j /output/inksight_svgs.zip ./*.svg 2>/dev/null || true
cd /app

# 3. 确定 IP 和端口
PORT="${INK_PORT:-8080}"
CONTAINER_IP=$(hostname -i 2>/dev/null || echo "localhost")
PLATFORM_URL="${INK_PLATFORM_URL:-}"

echo ""
echo "=========================================="
echo "  处理完成！"
echo "=========================================="
echo "  SVG 文件: $SVG_COUNT 个"
echo "  ZIP 包:   inksight_svgs.zip"
echo ""
echo "  HTTP 下载服务已启动:"
if [ -n "$PLATFORM_URL" ]; then
    echo "  平台地址: $PLATFORM_URL"
fi
echo "  容器地址: http://$CONTAINER_IP:$PORT/"
echo ""
echo "  下载方式 (在本地电脑执行):"
echo ""
echo "  查看文件列表:"
echo "    curl http://<容器地址>:8080/"
echo ""
echo "  下载单个SVG:"
echo "    curl -O http://<容器地址>:8080/A.svg"
echo ""
echo "  下载全部 + ZIP:"
echo "    wget -r -np http://<容器地址>:8080/"
echo "    curl -O http://<容器地址>:8080/inksight_svgs.zip"
echo ""
echo "  提示: 下载完记得在共绩算力控制台停止 Job，"
echo "        避免持续计费。"
echo "=========================================="

# 4. 启动 HTTP 服务（保持在 /output 目录）
cd /output
exec python3 -m http.server "$PORT"
