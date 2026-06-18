#!/usr/bin/env python3
"""
InkSight 手写字符参考表 → 原子化 SVG 转换器
=============================================
输入:  一张包含手写字符的图片 (A-Z, a-z, 0-9, 符号等)
处理:  OpenCV 分割每个字符 → InkSight 提取笔画轨迹 → 转 SVG
输出:  每个字符一个独立 SVG 文件，坐标映射回原图位置

无头 GPU 算力平台使用 (共绩算力 Job批处理)
"""

import argparse
import os
import re
import warnings
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
import tensorflow_text  # noqa: F401 — required for model loading
from huggingface_hub import from_pretrained_keras
from PIL import Image

warnings.filterwarnings("ignore")

# ======================== 常量 ========================

INPUT_SIZE = 224
MODEL_NAME = "Derendering/InkSight-Small-p"
PROMPT = "Recognize and derender."
FALLBACK_PROMPT = "Derender the ink."

# ======================== 笔画数据结构 ========================


class Stroke:
    """单笔笔画—连续的 x/y 坐标序列"""

    def __init__(self, list_of_coordinates=None):
        self.x: list[float] = []
        self.y: list[float] = []
        if list_of_coordinates:
            for pt in list_of_coordinates:
                self.x.append(float(pt[0]))
                self.y.append(float(pt[1]))

    def __len__(self):
        return len(self.x)

    def __getitem__(self, i):
        return (self.x[i], self.y[i])


class Ink:
    """多笔画容器—一个字符的全部笔画"""

    def __init__(self, list_of_strokes=None):
        self.strokes: list[Stroke] = list(list_of_strokes or [])

    def __len__(self):
        return len(self.strokes)

    def __getitem__(self, i):
        return self.strokes[i]


# ======================== InkSight 分词 / 反分词 ========================


def _text_to_tokens(text: str) -> list[int]:
    """从模型输出文本中提取 <ink_token_N> 数值序列"""
    return [int(t) for t in re.findall(r"<ink_token_(\d+)>", text)]


def _detokenize(tokens: list[int]) -> Ink:
    """将 token ID 序列还原为笔画坐标 (0 ~ INPUT_SIZE 范围内)"""
    npt = INPUT_SIZE + 1               # 每维 token 数
    vocab = npt * 2 + 1                # 词汇表大小
    start_tok = npt * 2                # 笔画分隔 token

    idx = 0
    stroke_groups = []
    cur = []

    while idx < len(tokens):
        t = tokens[idx]
        if t == start_tok:
            if cur:
                stroke_groups.append(cur)
            cur = []
            idx += 1
        elif idx + 1 < len(tokens) and tokens[idx + 1] != start_tok:
            x, y = t, tokens[idx + 1] - npt
            if 0 <= x <= INPUT_SIZE and 0 <= y <= INPUT_SIZE:
                cur.append((x, y))
            idx += 2
        else:
            idx += 1

    if cur:
        stroke_groups.append(cur)

    return Ink([Stroke(pts) for pts in stroke_groups])


# ======================== 图像分割 ========================


def segment_characters(
    image_path: str, padding: int = 5, min_area: int = 80
) -> tuple[list[tuple[int, int, int, int]], np.ndarray]:
    """
    用 OpenCV 轮廓检测找出图片中每个独立字符的包围盒。

    Returns:
        boxes: [(x, y, w, h), ...]  按先左后右、先上后下排序
        img:   原始 BGR 图像
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"❌ 无法读取图片: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 自适应二值化 (白底黑字场景)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 形态学去噪
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: list[tuple[int, int, int, int]] = []
    for c in contours:
        bx, by, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        if area < min_area:
            continue
        # 加边距
        bx = max(0, bx - padding)
        by = max(0, by - padding)
        bw = min(img.shape[1] - bx, bw + 2 * padding)
        bh = min(img.shape[0] - by, bh + 2 * padding)
        boxes.append((bx, by, bw, bh))

    if not boxes:
        print("⚠️  未检测到任何字符轮廓，请检查图片")
        return [], img

    # 先按 y 粗分 → 行分组 → 每行内按 x 排序
    boxes.sort(key=lambda b: (b[1], b[0]))
    rows: list[list[tuple[int, int, int, int]]] = []
    current_row = [boxes[0]]
    threshold = boxes[0][3] * 0.6

    for box in boxes[1:]:
        _, y, _, h = box
        row_y = current_row[0][1]
        if abs(y - row_y) < threshold:
            current_row.append(box)
            threshold = max(threshold, h * 0.6)
        else:
            rows.append(sorted(current_row, key=lambda b: b[0]))
            current_row = [box]
            threshold = h * 0.6

    rows.append(sorted(current_row, key=lambda b: b[0]))

    sorted_boxes = [box for row in rows for box in row]
    print(f"  → 共 {len(sorted_boxes)} 个字符，{len(rows)} 行")
    return sorted_boxes, img


def crop_and_pad(
    image: np.ndarray, box: tuple[int, int, int, int]
) -> tuple[Image.Image, float, int, int]:
    """
    裁切字符区域 → 保持比例缩放到 224 → 居中填充白底。

    Returns:
        padded:   224×224 PIL Image
        ratio:    缩放比例 (用于坐标反算)
        dx, dy:   填充偏移 (用于坐标反算)
    """
    x, y, w, h = box
    crop_bgr = image[y : y + h, x : x + w]
    crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(crop_rgb)

    ratio = min(INPUT_SIZE / w, INPUT_SIZE / h)
    new_w = int(round(w * ratio))
    new_h = int(round(h * ratio))
    pil_img = pil_img.resize((max(new_w, 1), max(new_h, 1)), Image.LANCZOS)

    padded = Image.new("RGB", (INPUT_SIZE, INPUT_SIZE), (255, 255, 255))
    dx = (INPUT_SIZE - pil_img.width) // 2
    dy = (INPUT_SIZE - pil_img.height) // 2
    padded.paste(pil_img, (dx, dy))
    return padded, ratio, dx, dy


# ======================== SVG 生成 ========================


def ink_to_svg(
    ink: Ink,
    box: tuple[int, int, int, int],
    ratio: float,
    dx: int,
    dy: int,
) -> str:
    """
    将 Ink 笔画数据转为 Blender Grease Pencil 兼容的 SVG。

    坐标映射回原图位置后，居中到 (0,0) 原点，
    使得 Blender 导入后每个字符都在原点，可直接排列。
    """
    x0, y0, w, h = box
    cx, cy = x0 + w / 2, y0 + h / 2
    pad = max(4, w * 0.1, h * 0.1)   # 边距，防止笔画被裁
    half_w, half_h = w / 2 + pad, h / 2 + pad

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' viewBox="{-half_w:.0f} {-half_h:.0f} {w+2*pad:.0f} {h+2*pad:.0f}">',
        '<g fill="none" stroke="#1a1a1a" stroke-width="2.0"',
        '   stroke-linecap="round" stroke-linejoin="round">',
    ]

    for stroke in ink.strokes:
        pts = []
        for px, py in zip(stroke.x, stroke.y):
            # 224 空间 → 原图坐标
            ox = (px - dx) / ratio + x0 if ratio > 0 else x0
            oy = (py - dy) / ratio + y0 if ratio > 0 else y0
            # 居中到原点
            ox -= cx
            oy -= cy
            pts.append(f"{ox:.2f},{oy:.2f}")
        if len(pts) >= 2:
            lines.append(f'  <path d="M {" L ".join(pts)}"/>')

    lines.append("</g></svg>")
    return "\n".join(lines)


# ======================== 模型推理 ========================


def load_model():
    """从 HuggingFace 加载 InkSight Small-p 模型。"""
    print("📥 加载 InkSight 模型…")
    model = from_pretrained_keras(MODEL_NAME)
    cf = model.signatures["serving_default"]
    print(f"   ✅ 模型就绪 ({MODEL_NAME})")
    return cf


def _extract_recognized_text(raw_output: str) -> str:
    """从模型输出中提取识别到的文本（<ink_token_ 之前的部分）。"""
    m = re.split(r"<ink_token_\d+>", raw_output)
    if m:
        text = m[0].strip()
        # 清除可能的特殊标记
        text = re.sub(r"\s+", "", text)
        return text
    return ""


def run_inference(
    cf, pil_image: Image.Image
) -> tuple[Ink, str]:
    """
    对单个字符执行 InkSight 推理。

    Returns:
        (ink, recognized_text)
        ink: 224×224 空间的笔画数据
        recognized_text: 模型识别出的字符文本
    """
    img_np = np.array(pil_image)[:, :, :3]
    encoded = tf.reshape(tf.io.encode_jpeg(img_np), (1, 1))

    # 主推理 (Recognize and Derender)
    inp = tf.constant([PROMPT], dtype=tf.string)
    out = cf(input_text=inp, **{"image/encoded": encoded})
    text = out["output_0"].numpy()[0][0].decode()
    ink = _detokenize(_text_to_tokens(text))
    recognized = _extract_recognized_text(text)

    # 空输出时 fallback
    if len(ink.strokes) == 0:
        inp = tf.constant([FALLBACK_PROMPT], dtype=tf.string)
        out = cf(input_text=inp, **{"image/encoded": encoded})
        text = out["output_0"].numpy()[0][0].decode()
        ink = _detokenize(_text_to_tokens(text))
        recognized = _extract_recognized_text(text)

    return ink, recognized


# ======================== 入口 ========================


def main():
    parser = argparse.ArgumentParser(
        description="InkSight 手写字符 → 原子化 SVG"
    )
    parser.add_argument(
        "--input",
        default="inksight.jpg",
        help="输入图片路径 (默认: inksight.jpg)",
    )
    parser.add_argument(
        "--output",
        default="/output",
        help="输出目录 (默认: /output)",
    )
    parser.add_argument(
        "--min-area",
        type=int,
        default=80,
        help="最小字符轮廓面积 (默认: 80, 过滤噪点)",
    )
    args = parser.parse_args()

    # 确保输出目录
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 输出目录: {out_dir.resolve()}")

    # 1. 加载模型
    cf = load_model()

    # 2. 分割字符
    print(f"🔍 分割字符: {args.input}")
    if not os.path.isfile(args.input):
        print(f"❌ 图片不存在: {args.input}")
        sys.exit(1)
    boxes, img = segment_characters(args.input, min_area=args.min_area)
    if not boxes:
        print("❌ 未找到任何字符，退出")
        sys.exit(1)

    # 3. 逐字符推理
    print(f"🖌️  推理 {len(boxes)} 个字符…")
    results = []          # (ink, box, ratio, dx, dy, recognized_text)
    for i, box in enumerate(boxes, 1):
        # crop → pad
        char_pil, ratio, dx, dy = crop_and_pad(img, box)
        # inference
        ink, recognized = run_inference(cf, char_pil)
        results.append((ink, box, ratio, dx, dy, recognized))

        if i % 10 == 0 or i == len(boxes):
            print(f"   {i}/{len(boxes)}")

    # 4. 输出 SVG（优先用识别文本命名）
    print("💾 写入 SVG 文件…")
    used_names: set[str] = set()

    for i, (ink, box, ratio, dx, dy, recognized) in enumerate(results, 1):
        svg = ink_to_svg(ink, box, ratio, dx, dy)

        # 文件名：识别文本（去重）或 fallback 到序号
        if recognized and recognized.strip():
            base = recognized.strip()
            if base in used_names:
                base = f"{base}_{i}"
        else:
            base = f"char_{i:03d}"
        used_names.add(base)
        fname = out_dir / f"{base}.svg"
        fname.write_text(svg, encoding="utf-8")

    print(f"\n✅ 完成！共 {len(results)} 个 SVG 文件")
    print(f"   位置: {out_dir.resolve()}")

    # 输出映射表
    print("\n——— 字符 → 文件映射 ———")
    used_names.clear()
    for i, (ink, box, ratio, dx, dy, recognized) in enumerate(results, 1):
        if recognized and recognized.strip():
            base = recognized.strip()
            if base in used_names:
                base = f"{base}_{i}"
        else:
            base = f"char_{i:03d}"
        used_names.add(base)
        print(f"  {base}.svg  ←  识别=[{recognized}]  位置=({box[0]},{box[1]} {box[2]}×{box[3]})")


if __name__ == "__main__":
    main()
