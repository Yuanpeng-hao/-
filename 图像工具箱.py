# -*- coding: utf-8 -*-
"""
图像工具箱 v2 —— 一个程序搞定图片压缩与常用处理
=========================================================
功能一览
  ▣ 压缩 · 缩放   按质量压缩 / 按指定文件大小自动逼近 / 长边、宽高、百分比缩放
  ⇄ 格式转换      JPG / PNG / WEBP / BMP / TIFF / GIF / ICO / TGA / PPM 互转
                  （装了 pillow-heif / pillow-avif 则自动支持 HEIC、AVIF）
  ✂ 裁剪 · 旋转   自定义像素裁剪、居中比例裁剪、旋转、镜像、加边框
  ▦ 水印          文字水印 / 图片水印，9 宫格定位、透明度、平铺
  ⌗ 拼接          多张图纵向或横向拼成长图
  ⚙ 其他          批量重命名、清除 EXIF、查看图片信息
  ◎ 通用          指定输出文件大小上限 / 动图整段处理 / 实时预览 / 右键菜单 / 快捷键

运行环境：Python 3.8+，仅依赖 Pillow
安装依赖：pip install pillow
可选增强：pip install pillow-heif pillow-avif   # 支持 HEIC / AVIF
启动：    python 图像工具箱.py

快捷键：Ctrl+O 添加图片 | Ctrl+Shift+O 添加文件夹 | Ctrl+Enter 开始处理
        Esc 停止 | Delete 移除选中 | Ctrl+E 预估体积 | 双击列表用系统看图器打开
"""

import io
import json
import os
import queue
import shutil
import sys
import threading
from datetime import datetime

try:
    from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps
except ImportError:  # pragma: no cover
    sys.stderr.write("缺少依赖 Pillow，请先执行：pip install pillow\n")
    raise

# ---------- 可选插件：HEIC / AVIF ----------
HAS_HEIF = False
HAS_AVIF = False
try:                                    # HEIC / HEIF
    import pillow_heif
    pillow_heif.register_heif_opener()
    HAS_HEIF = True
except Exception:
    pass
try:                                    # AVIF（Pillow ≥ 11.3 原生支持，或 pillow-avif）
    import pillow_avif  # noqa: F401
    HAS_AVIF = True
except Exception:
    try:
        import warnings
        from PIL import features
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            HAS_AVIF = bool(features.check("avif"))
    except Exception:
        HAS_AVIF = False

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

try:
    from PIL import ImageTk
    HAS_IMAGETK = True
except Exception:                       # 极少数环境缺少 tkinter 支持
    HAS_IMAGETK = False


# ==========================================================================
# 常量
# ==========================================================================
BASE_EXTS = (".jpg", ".jpeg", ".jfif", ".jpe", ".png", ".webp", ".bmp",
             ".tif", ".tiff", ".gif", ".tga", ".ico", ".pcx",
             ".ppm", ".pgm", ".pbm", ".pnm", ".dds")
IMAGE_EXTS = BASE_EXTS
if HAS_HEIF:
    IMAGE_EXTS += (".heic", ".heif")
if HAS_AVIF:
    IMAGE_EXTS += (".avif",)

FILE_TYPES = [("图片文件", "*" + " *".join(BASE_EXTS) +
               (" *.heic *.heif" if HAS_HEIF else "") +
               (" *.avif" if HAS_AVIF else "")),
              ("所有文件", "*.*")]

FMT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp",
           "TIFF": ".tif", "GIF": ".gif", "ICO": ".ico", "TGA": ".tga",
           "PPM": ".ppm", "AVIF": ".avif", "HEIC": ".heic"}
EXT_FMT = {".jpg": "JPEG", ".jpeg": "JPEG", ".jfif": "JPEG", ".jpe": "JPEG",
           ".png": "PNG", ".webp": "WEBP", ".bmp": "BMP",
           ".tif": "TIFF", ".tiff": "TIFF", ".gif": "GIF", ".tga": "TGA",
           ".ppm": "PPM", ".pgm": "PPM", ".pbm": "PPM", ".pnm": "PPM",
           ".pcx": "PNG", ".ico": "PNG", ".dds": "PNG"}
if HAS_HEIF:
    EXT_FMT[".heic"] = "HEIC"
    EXT_FMT[".heif"] = "HEIC"
if HAS_AVIF:
    EXT_FMT[".avif"] = "AVIF"

QUALITY_FORMATS = ("JPEG", "WEBP", "AVIF", "HEIC")   # 用质量参数
PALETTE_FORMATS = ("PNG", "GIF")                     # 用颜色数参数


def output_formats():
    fmts = ["保持原格式", "JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF", "ICO", "TGA", "PPM"]
    if HAS_AVIF:
        fmts.append("AVIF")
    if HAS_HEIF:
        fmts.append("HEIC")
    return fmts


POS_CHOICES = ["左上", "上中", "右上", "左中", "居中", "右中", "左下", "下中", "右下"]
SIZE_UNITS = {"B": 1, "K": 1024, "KB": 1024, "M": 1024 * 1024, "MB": 1024 * 1024}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".image_toolbox_settings.json")


# ==========================================================================
# 基础工具
# ==========================================================================
def _int(value, default=0):
    try:
        text = str(value).strip()
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        text = str(value).strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _rgb(value, default=(255, 255, 255)):
    text = str(value).strip()
    if not text:
        return default
    if text.count(",") == 2:
        parts = [_int(p, 255) for p in text.split(",")]
    else:
        try:
            parts = ImageColor.getrgb(text)
        except ValueError:
            return default
    return tuple(max(0, min(255, int(c))) for c in parts[:3])


def load_font(size):
    size = max(8, int(size))
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def human_size(num_bytes):
    if num_bytes < 1024:
        return "%d B" % num_bytes
    if num_bytes < 1024 * 1024:
        return "%.1f KB" % (num_bytes / 1024)
    return "%.2f MB" % (num_bytes / 1024 / 1024)


def parse_size(text, default_unit="KB"):
    """'300' / '300KB' / '1.5MB' / '2M' → 字节数，无法解析返回 0"""
    raw = str(text).strip().upper().replace(" ", "").replace(",", "")
    if not raw:
        return 0
    unit, number = default_unit.upper(), raw
    for suffix in ("MB", "KB", "M", "K", "B"):
        if raw.endswith(suffix) and len(raw) > len(suffix):
            number, unit = raw[:-len(suffix)], suffix
            break
    try:
        value = float(number)
    except ValueError:
        return 0
    return int(value * SIZE_UNITS.get(unit, 1024)) if value > 0 else 0


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    index = 1
    while os.path.exists("%s_%d%s" % (base, index, ext)):
        index += 1
    return "%s_%d%s" % (base, index, ext)


def resolve_format(cfg_fmt, src_path):
    if cfg_fmt and cfg_fmt != "保持原格式":
        return cfg_fmt
    return EXT_FMT.get(os.path.splitext(src_path)[1].lower(), "JPEG")


def _default_param(fmt, cfg):
    if fmt in QUALITY_FORMATS:
        return _int(cfg.get("quality"), 85)
    if fmt == "GIF":
        return _int(cfg.get("png_colors"), 256)
    if fmt == "PNG":
        return _int(cfg.get("png_colors"), 128) if cfg.get("png_quant") else 256
    return None


# ==========================================================================
# 像素处理
# ==========================================================================
def flatten(im, bg=(255, 255, 255)):
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        base = Image.new("RGB", im.size, bg)
        rgba = im.convert("RGBA")
        base.paste(rgba, (0, 0), rgba)
        return base
    if im.mode == "RGB":
        return im
    return im.convert("RGB")


def quantize_png(im, colors):
    colors = max(2, min(256, int(colors)))
    try:
        if im.mode in ("RGBA", "LA", "PA", "P"):
            return im.convert("RGBA").quantize(colors=colors, method=Image.FASTOCTREE)
        return im.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT)
    except (ValueError, OSError):
        return im


def op_crop(im, cfg):
    mode = cfg.get("crop_mode", "不裁剪")
    if mode == "自定义像素":
        left, top = _int(cfg.get("crop_l"), 0), _int(cfg.get("crop_t"), 0)
        width, height = _int(cfg.get("crop_w"), 0), _int(cfg.get("crop_h"), 0)
        right = left + width if width > 0 else im.width
        bottom = top + height if height > 0 else im.height
        left, top = max(0, left), max(0, top)
        right, bottom = min(im.width, right), min(im.height, bottom)
        if right - left >= 1 and bottom - top >= 1:
            return im.crop((left, top, right, bottom))
    elif mode == "居中比例":
        text = str(cfg.get("crop_ratio", "1:1")).replace("：", ":")
        try:
            rw, rh = [float(v) for v in text.split(":")[:2]]
        except ValueError:
            rw, rh = 1.0, 1.0
        if rw <= 0 or rh <= 0:
            return im
        target, width, height = rw / rh, im.width, im.height
        if width / height > target:
            new_w = int(round(height * target))
            left = (width - new_w) // 2
            return im.crop((left, 0, left + new_w, height))
        new_h = int(round(width / target))
        top = (height - new_h) // 2
        return im.crop((0, top, width, top + new_h))
    return im


def op_rotate(im, cfg):
    mode = cfg.get("rot_mode", "不旋转")
    angle = {"顺时针90°": -90, "180°": 180, "逆时针90°": 90}.get(mode)
    if mode == "自定义角度":
        angle = -_float(cfg.get("rot_angle"), 0.0)
    if angle and abs(angle) > 0.01:
        fill = (0, 0, 0, 0) if im.mode in ("RGBA", "LA") else None
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill)
    flip = cfg.get("flip", "不翻转")
    if flip == "水平镜像":
        im = ImageOps.mirror(im)
    elif flip == "垂直镜像":
        im = ImageOps.flip(im)
    return im


def op_resize(im, cfg):
    mode = cfg.get("rs_mode", "不缩放")
    width, height = im.size
    if mode == "长边限制":
        long_side = _int(cfg.get("rs_long"), 0)
        if long_side <= 0 or max(width, height) <= long_side:
            return im
        scale = long_side / float(max(width, height))
        return im.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    if mode == "指定宽高":
        tw, th = _int(cfg.get("rs_w"), 0), _int(cfg.get("rs_h"), 0)
        if tw <= 0 and th <= 0:
            return im
        if cfg.get("rs_keep", True):
            if tw > 0 and th > 0:
                scale = min(tw / float(width), th / float(height))
            elif tw > 0:
                scale = tw / float(width)
            else:
                scale = th / float(height)
            return im.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
        return im.resize((tw if tw > 0 else width, th if th > 0 else height), Image.LANCZOS)
    if mode == "按百分比":
        pct = _float(cfg.get("rs_pct"), 100.0)
        if pct <= 0 or abs(pct - 100.0) < 1e-6:
            return im
        return im.resize((max(1, round(width * pct / 100.0)), max(1, round(height * pct / 100.0))), Image.LANCZOS)
    return im


def op_border(im, cfg):
    width = _int(cfg.get("border_width"), 0)
    if width <= 0:
        return im
    color = _rgb(cfg.get("border_color"), (255, 255, 255))
    if im.mode in ("RGBA", "LA"):
        color = color + (255,)
    return ImageOps.expand(im, border=width, fill=color)


def _anchor(canvas_size, item_size, pos, margin):
    cw, ch = canvas_size
    iw, ih = item_size
    pos = str(pos or "右下")
    vertical = "上" if "上" in pos else ("下" if "下" in pos else "中")
    horizontal = "左" if "左" in pos else ("右" if "右" in pos else "中")
    x = {"左": margin, "中": (cw - iw) // 2, "右": cw - iw - margin}.get(horizontal, (cw - iw) // 2)
    y = {"上": margin, "中": (ch - ih) // 2, "下": ch - ih - margin}.get(vertical, (ch - ih) // 2)
    return max(0, min(cw - iw, x)), max(0, min(ch - ih, y))


def op_watermark(im, cfg):
    margin = _int(cfg.get("wm_margin"), 20)
    if cfg.get("wm_type", "文字水印") == "文字水印":
        text = str(cfg.get("wm_text", "")).strip()
        if not text:
            return im
        base = im.convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font = load_font(_int(cfg.get("wm_size"), 40))
        color = _rgb(cfg.get("wm_color"), (255, 255, 255))
        alpha = int(255 * max(0, min(100, _int(cfg.get("wm_opacity"), 60))) / 100.0)
        ink = (color[0], color[1], color[2], alpha)
        box = draw.textbbox((0, 0), text, font=font)
        tw, th = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        if cfg.get("wm_tile", False):
            step_x, step_y = tw + margin * 2, th + margin * 2
            for y in range(0, base.height, max(1, step_y)):
                for x in range(0, base.width, max(1, step_x)):
                    draw.text((x - box[0], y - box[1]), text, font=font, fill=ink)
        else:
            x, y = _anchor(base.size, (tw, th), cfg.get("wm_pos", "右下"), margin)
            draw.text((x - box[0], y - box[1]), text, font=font, fill=ink)
        return Image.alpha_composite(base, layer)

    mark_path = str(cfg.get("wm_image", "")).strip()
    if not mark_path or not os.path.exists(mark_path):
        return im
    base = im.convert("RGBA")
    mark = Image.open(mark_path)
    mark = ImageOps.exif_transpose(mark) or mark
    mark = mark.convert("RGBA")
    scale = max(1, _int(cfg.get("wm_image_scale"), 20)) / 100.0
    mark = mark.resize((max(1, round(mark.width * scale)), max(1, round(mark.height * scale))), Image.LANCZOS)
    alpha = max(0, min(100, _int(cfg.get("wm_opacity"), 60))) / 100.0
    if alpha < 1.0:
        mark.putalpha(mark.getchannel("A").point(lambda v: int(v * alpha)))
    if cfg.get("wm_tile", False):
        step_x, step_y = mark.width + margin * 2, mark.height + margin * 2
        for y in range(margin, base.height, max(1, step_y)):
            for x in range(margin, base.width, max(1, step_x)):
                base.alpha_composite(mark, (x, y))
        return base
    x, y = _anchor(base.size, mark.size, cfg.get("wm_pos", "右下"), margin)
    base.alpha_composite(mark, (x, y))
    return base


# ==========================================================================
# 图像载荷（支持动图多帧）
# ==========================================================================
class Payload:
    """一帧或多帧图像，外加动画每帧时长与 EXIF"""

    def __init__(self, frames, durations=None, exif=None):
        self.frames = frames
        self.durations = durations or [100] * len(frames)
        self.exif = exif

    @property
    def first(self):
        return self.frames[0]

    @property
    def size(self):
        return self.frames[0].size

    @property
    def animated(self):
        return len(self.frames) > 1

    def scaled(self, factor):
        if abs(factor - 1.0) < 1e-6:
            return self
        frames = [f.resize((max(1, round(f.width * factor)), max(1, round(f.height * factor))),
                           Image.LANCZOS) for f in self.frames]
        return Payload(frames, self.durations, self.exif)


def load_payload(path, cfg):
    im = Image.open(path)
    exif = None if cfg.get("strip_exif", True) else im.info.get("exif")
    animated = bool(getattr(im, "is_animated", False)) and getattr(im, "n_frames", 1) > 1
    frames, durations = [], []
    if animated:
        for index in range(im.n_frames):
            im.seek(index)
            frames.append(im.convert("RGBA"))
            durations.append(max(20, int(im.info.get("duration") or 100)))
    else:
        try:
            im.seek(0)
        except (EOFError, AttributeError):
            pass
        frames.append(im.copy())
        durations.append(100)
    # 静态图按 EXIF 方向摆正（动图逐帧处理）
    if cfg.get("auto_orient", True):
        for index, frame in enumerate(frames):
            transposed = ImageOps.exif_transpose(frame)
            if transposed is not None:
                frames[index] = transposed
    return Payload(frames, durations, exif)


def render_payload(payload, cfg):
    frames = []
    for frame in payload.frames:
        out = op_crop(frame, cfg)
        out = op_rotate(out, cfg)
        out = op_resize(out, cfg)
        out = op_border(out, cfg)
        out = op_watermark(out, cfg)
        frames.append(out)
    return Payload(frames, payload.durations, payload.exif)


def encode_payload(payload, fmt, param, cfg):
    fmt = fmt.upper()
    bg = _rgb(cfg.get("bg"), (255, 255, 255))
    buf = io.BytesIO()
    if fmt == "GIF":
        colors = max(2, min(256, int(param or 256)))
        frames = [flatten(f, bg).convert("P", palette=Image.ADAPTIVE, colors=colors)
                  for f in payload.frames]
        duration = payload.durations if payload.animated else payload.durations[0]
        frames[0].save(buf, format="GIF", save_all=payload.animated, append_images=frames[1:],
                       duration=duration, loop=0, optimize=True, disposal=2)
    elif fmt == "JPEG":
        kw = {"format": "JPEG", "optimize": True, "progressive": True}
        if param:
            kw["quality"] = max(1, min(100, int(param)))
        if payload.exif:
            kw["exif"] = payload.exif
        flatten(payload.first, bg).save(buf, **kw)
    elif fmt == "WEBP":
        img = payload.first if payload.first.mode in ("RGB", "RGBA") else payload.first.convert("RGBA")
        kw = {"format": "WEBP", "method": 5}
        if param:
            kw["quality"] = max(1, min(100, int(param)))
        img.save(buf, **kw)
    elif fmt == "PNG":
        img = payload.first
        if param and int(param) < 256:
            img = quantize_png(img, int(param))
        img.save(buf, format="PNG", optimize=True, compress_level=9)
    elif fmt == "BMP":
        flatten(payload.first, bg).save(buf, format="BMP")
    elif fmt == "TIFF":
        payload.first.save(buf, format="TIFF", compression="tiff_deflate")
    elif fmt == "TGA":
        (flatten(payload.first, bg) if payload.first.mode not in ("RGB", "RGBA") else payload.first
         ).save(buf, format="TGA")
    elif fmt == "PPM":
        flatten(payload.first, bg).save(buf, format="PPM")
    elif fmt == "ICO":
        img = payload.first.convert("RGBA")
        side = max(16, min(256, max(img.size)))
        img = img.resize((side, side), Image.LANCZOS) if img.size != (side, side) else img
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side]
        img.save(buf, format="ICO", sizes=sizes or [(side, side)])
    elif fmt == "AVIF":
        kw = {"format": "AVIF"}
        if param:
            kw["quality"] = max(1, min(100, int(param)))
        payload.first.convert("RGB").save(buf, **kw)
    elif fmt == "HEIC":
        kw = {"format": "HEIF"}
        if param:
            kw["quality"] = max(1, min(100, int(param)))
        payload.first.convert("RGB").save(buf, **kw)
    else:
        raise ValueError("不支持的输出格式：%s" % fmt)
    return buf.getvalue()


def _best_param(payload, fmt, cfg):
    """不超目标体积的最优参数，返回 (字节, 参数)"""
    target = cfg.get("target_bytes") or 0
    if not target:
        param = _default_param(fmt, cfg)
        return encode_payload(payload, fmt, param, cfg), param

    if fmt in QUALITY_FORMATS:
        if len(encode_payload(payload, fmt, 95, cfg)) <= target:
            return encode_payload(payload, fmt, 95, cfg), 95
        best, low, high = None, 1, 95
        while low <= high:
            mid = (low + high) // 2
            data = encode_payload(payload, fmt, mid, cfg)
            if len(data) <= target:
                best, low = (data, mid), mid + 1
            else:
                high = mid - 1
        if best:
            return best
        return encode_payload(payload, fmt, 1, cfg), 1

    if fmt in PALETTE_FORMATS:
        for colors in (256, 192, 128, 96, 64, 48, 32, 24, 16, 12, 8, 4, 2):
            try:
                data = encode_payload(payload, fmt, colors, cfg)
            except (ValueError, OSError):
                continue
            if len(data) <= target:
                return data, colors
        return encode_payload(payload, fmt, 2, cfg), 2

    return encode_payload(payload, fmt, None, cfg), None     # BMP/TGA/TIFF/ICO/PPM 只能缩尺寸


def _quick_size(payload, fmt, cfg):
    if fmt in QUALITY_FORMATS:
        return len(encode_payload(payload, fmt, 70, cfg))
    if fmt in PALETTE_FORMATS:
        return len(encode_payload(payload, fmt, 96, cfg))
    return len(encode_payload(payload, fmt, None, cfg))


def compress_to_target(payload, fmt, cfg, log=None):
    """压到不超过目标体积：先降质量，再二分缩放。返回 (字节, 最终尺寸, 说明)"""
    target = cfg.get("target_bytes") or 0
    if not target:
        data, _ = _best_param(payload, fmt, cfg)
        return data, payload.size, ""

    data, param = _best_param(payload, fmt, cfg)
    if len(data) <= target:
        if fmt in QUALITY_FORMATS and param == 95:
            return data, payload.size, "原图已小于目标，按最高质量输出"
        return data, payload.size, ""

    if not cfg.get("allow_resize", True):
        if log:
            log("      已达该格式最低质量仍超出目标，且未开启自动缩小尺寸")
        return data, payload.size, "超出目标（未开启自动缩小尺寸）"

    best_scale, low, high = None, 0.02, 1.0
    for _ in range(10):
        mid = (low + high) / 2.0
        if _quick_size(payload.scaled(mid), fmt, cfg) <= target:
            best_scale, low = mid, mid
        else:
            high = mid

    scale = best_scale or 0.02
    cand = payload
    for _ in range(6):
        cand = payload.scaled(scale)
        data, _ = _best_param(cand, fmt, cfg)
        if len(data) <= target:
            if log and cand.size != payload.size:
                log("      为达目标体积自动缩放至 %dx%d" % cand.size)
            return data, cand.size, "自动缩放至 %dx%d" % cand.size
        scale *= 0.85

    if log:
        log("      目标实在太小，已输出该格式下的极限结果")
    return data, cand.size, "目标过小，已输出极限结果"


# ==========================================================================
# 其它核心功能
# ==========================================================================
def stitch_images(images, cfg):
    direction = cfg.get("st_dir", "垂直拼接")
    gap = max(0, _int(cfg.get("st_gap"), 0))
    bg = _rgb(cfg.get("st_bg"), (255, 255, 255))
    unify = cfg.get("st_unify", True)
    count = len(images)

    if direction == "垂直拼接":
        ref = max(img.width for img in images)
        if unify:
            images = [img.resize((ref, max(1, round(img.height * ref / float(img.width)))), Image.LANCZOS)
                      for img in images]
        total_h = sum(img.height for img in images) + gap * (count - 1)
        canvas = Image.new("RGB", (ref, total_h), bg)
        y = 0
        for img in images:
            canvas.paste(flatten(img, bg), ((ref - img.width) // 2, y))
            y += img.height + gap
        return canvas

    ref = max(img.height for img in images)
    if unify:
        images = [img.resize((max(1, round(img.width * ref / float(img.height))), ref), Image.LANCZOS)
                  for img in images]
    total_w = sum(img.width for img in images) + gap * (count - 1)
    canvas = Image.new("RGB", (total_w, ref), bg)
    x = 0
    for img in images:
        canvas.paste(flatten(img, bg), (x, (ref - img.height) // 2))
        x += img.width + gap
    return canvas


def describe(path):
    with Image.open(path) as im:
        lines = ["%-30s %s" % (os.path.basename(path), human_size(os.path.getsize(path)))]
        frames = getattr(im, "n_frames", 1)
        lines.append("      格式 %s | 尺寸 %dx%d | 模式 %s | 帧数 %s%s"
                     % (im.format, im.width, im.height, im.mode, frames,
                        "（动图）" if frames > 1 else ""))
        dpi = im.info.get("dpi")
        if dpi:
            lines.append("      DPI %s x %s" % (round(dpi[0]), round(dpi[1])))
        lines.append("      EXIF 元数据：%s" % ("有" if im.info.get("exif") else "无"))
    return lines


# ==========================================================================
# 界面
# ==========================================================================
class ImageToolbox:
    def __init__(self, root):
        self.root = root
        self.root.title("图像工具箱  ▣  压缩 · 转换 · 裁剪 · 水印 · 拼接")
        # 按屏幕大小自适应，避免小屏笔记本上窗口超出屏幕
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = max(900, min(1140, screen_w - 60))
        win_h = max(480, min(880, screen_h - 110))
        self.root.geometry("%dx%d+%d+%d" % (win_w, win_h, (screen_w - win_w) // 2, max(0, (screen_h - win_h) // 2 - 20)))
        self.root.minsize(900, 460)

        self.files = []
        self.msg_queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.busy = False
        self.scanning = set()
        self._preview_img = None
        self.start_time = None
        self._vbar_shown = False

        self._build_header()
        self._build_status()
        self._build_scroll_area()
        self._build_files()
        self._build_notebook()
        self._build_bottom()
        self._build_log()
        self._bind_events()
        self._load_settings()
        self._toggle_limit()
        self._refresh_limits_note()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()
        self.root.after_idle(lambda: self._bind_wheel(self.scroll_inner))

    # ---------------------------------------------------------- 顶部标题
    def _build_header(self):
        bar = tk.Frame(self.root, bg="#1f6feb")
        bar.pack(fill="x")
        tk.Label(bar, text=" ▣  图像工具箱", bg="#1f6feb", fg="white",
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left", padx=(10, 6), pady=6)
        extras = []
        if HAS_HEIF:
            extras.append("HEIC")
        if HAS_AVIF:
            extras.append("AVIF")
        tip = "支持动画 GIF%s ｜ 大小上限 · 实时预览 · 快捷键" % (
            ("、" + "、".join(extras)) if extras else "")
        tk.Label(bar, text=tip, bg="#1f6feb", fg="#d7e6ff",
                 font=("Microsoft YaHei UI", 9)).pack(side="right", padx=12)

    # ---------------------------------------------------------- 创建可滚动区域
    def _build_scroll_area(self):
        # 外层容器：header 与 status 之间的全部内容都放进来，内容超高时右侧出现滚动条
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        self.scroll_canvas = tk.Canvas(outer, highlightthickness=0, bd=0)
        self.scroll_canvas.grid(row=0, column=0, sticky="nsew")

        self.scroll_vbar = ttk.Scrollbar(outer, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_vbar.grid(row=0, column=1, sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=self.scroll_vbar.set)

        self.scroll_inner = ttk.Frame(self.scroll_canvas)
        self.scroll_window = self.scroll_canvas.create_window((0, 0), window=self.scroll_inner, anchor="nw")

        self.scroll_inner.bind("<Configure>", self._on_scroll_content)
        self.scroll_canvas.bind("<Configure>", self._on_scroll_canvas)
        self.scroll_canvas.bind("<MouseWheel>", self._on_scroll_wheel)

        self.root.after_idle(self._sync_scrollbar)

    def _on_scroll_content(self, _event=None):
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))
        self.root.after_idle(self._sync_scrollbar)

    def _on_scroll_canvas(self, event):
        # 内嵌内容始终与画布同宽，避免横向被裁切
        self.scroll_canvas.itemconfigure(self.scroll_window, width=event.width)
        self.root.after_idle(self._sync_scrollbar)

    def _sync_scrollbar(self):
        """内容高度超过可视区域时才显示右侧滚动条"""
        if not hasattr(self, "scroll_canvas"):
            return
        content_h = self.scroll_inner.winfo_reqheight()
        view_h = self.scroll_canvas.winfo_height()
        need = content_h > view_h + 2
        if need and not self._vbar_shown:
            self.scroll_vbar.grid()
            self._vbar_shown = True
        elif not need and self._vbar_shown:
            self.scroll_vbar.grid_remove()
            self._vbar_shown = False
            self.scroll_canvas.yview_moveto(0)

    def _on_scroll_wheel(self, event):
        if self._vbar_shown:
            self.scroll_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _bind_wheel(self, widget):
        """给普通控件补上滚轮支持（列表/文本框/下拉框保留各自的滚动）"""
        if isinstance(widget, (ttk.Treeview, tk.Text, ttk.Combobox, tk.Listbox,
                               ttk.Scale, tk.Scale)):
            return
        widget.bind("<MouseWheel>", self._on_scroll_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_wheel(child)

    # ---------------------------------------------------------- 文件列表
    def _build_files(self):
        wrapper = ttk.LabelFrame(self.scroll_inner, text=" ▤ 待处理图片（单击预览，双击用系统看图器打开） ")
        wrapper.pack(fill="both", expand=True, padx=10, pady=(8, 4))

        body = ttk.Frame(wrapper)
        body.pack(fill="both", expand=True, padx=8, pady=8)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew")

        self.tree = ttk.Treeview(left, columns=("size", "bytes", "fmt"), show="tree headings",
                                 selectmode="extended", height=5)
        self.tree.heading("#0", text="文件名", anchor="w")
        self.tree.heading("size", text="尺寸", anchor="center")
        self.tree.heading("bytes", text="体积", anchor="center")
        self.tree.heading("fmt", text="格式", anchor="center")
        self.tree.column("#0", width=330, anchor="w")
        self.tree.column("size", width=110, anchor="center", stretch=False)
        self.tree.column("bytes", width=90, anchor="center", stretch=False)
        self.tree.column("fmt", width=66, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        tools = ttk.Frame(left)
        tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(tools, text="＋ 添加图片", width=12, command=self.add_files).pack(side="left")
        ttk.Button(tools, text="▤ 添加文件夹", width=13, command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(tools, text="▸ 只处理选中", width=13, command=lambda: self._start(only_selected=True)).pack(side="left", padx=4)
        ttk.Button(tools, text="✕ 移除选中", width=12, command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(tools, text="⌫ 清空", width=8, command=self.clear_files).pack(side="left")
        self.count_label = ttk.Label(tools, text="共 0 张", foreground="#1f6feb")
        self.count_label.pack(side="right")

        # 预览面板
        right = ttk.LabelFrame(body, text=" ▣ 预览 ")
        right.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        self.preview_label = tk.Label(right, text="点击左侧图片查看预览", width=28, height=9,
                                      bg="#f4f6f8", fg="#8a8f98", relief="flat")
        self.preview_label.pack(padx=8, pady=(8, 4))
        self.preview_info = tk.Label(right, text="—", justify="left", anchor="w",
                                     font=("Microsoft YaHei UI", 9), fg="#3a3f47")
        self.preview_info.pack(fill="x", padx=10, pady=(0, 8))

        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="查看大图（系统看图器）", command=self._open_in_viewer)
        self.menu.add_command(label="在资源管理器中显示", command=self._reveal_in_explorer)
        self.menu.add_command(label="复制文件路径", command=self._copy_path)
        self.menu.add_separator()
        self.menu.add_command(label="移除选中", command=self.remove_selected)
        self.tree.bind("<Button-3>", self._popup_menu)

    # ---------------------------------------------------------- 功能页
    def _build_notebook(self):
        self.nb = ttk.Notebook(self.scroll_inner)
        self.nb.pack(fill="both", expand=True, padx=10, pady=4)
        self._tab_compress()
        self._tab_convert()
        self._tab_crop()
        self._tab_watermark()
        self._tab_stitch()
        self._tab_other()

    @staticmethod
    def _grid_row(parent, row, label, widget, hint=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(14, 10), pady=5)
        widget.grid(row=row, column=1, sticky="w", pady=5)
        if hint:
            ttk.Label(parent, text=hint, foreground="#8a8f98").grid(row=row, column=2, sticky="w", padx=8, pady=5)

    def _slider_row(self, parent, var, from_, to, label_text, hint=""):
        box = ttk.Frame(parent)
        value_label = ttk.Label(box, text=str(var.get()), width=4, foreground="#1f6feb")

        def sync(_=None):
            value_label.config(text=str(var.get()))

        ttk.Scale(box, from_=from_, to=to, variable=var, orient="horizontal", length=250,
                  command=sync).pack(side="left")
        value_label.pack(side="left", padx=6)
        if hint:
            ttk.Label(box, text=hint, foreground="#8a8f98").pack(side="left", padx=4)
        return box

    def _tab_compress(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ▣ 压缩 · 缩放  ")

        self.v_rs_mode = tk.StringVar(value="长边限制")
        self.v_rs_long = tk.StringVar(value="1920")
        self.v_rs_w = tk.StringVar(value="1920")
        self.v_rs_h = tk.StringVar(value="1080")
        self.v_rs_pct = tk.StringVar(value="70")
        self.v_rs_keep = tk.BooleanVar(value=True)
        self.v_c_fmt = tk.StringVar(value="保持原格式")
        self.v_c_quality = tk.IntVar(value=85)
        self.v_c_png_quant = tk.BooleanVar(value=False)
        self.v_c_png_colors = tk.StringVar(value="128")

        row = 0
        self._grid_row(tab, row, "缩放方式", ttk.Combobox(tab, textvariable=self.v_rs_mode, width=16,
                                                      state="readonly",
                                                      values=["不缩放", "长边限制", "指定宽高", "按百分比"])); row += 1
        self._grid_row(tab, row, "长边不超过", ttk.Entry(tab, textvariable=self.v_rs_long, width=18),
                       "像素（超出才缩小，不放大）"); row += 1
        wh = ttk.Frame(tab)
        ttk.Entry(wh, textvariable=self.v_rs_w, width=8).pack(side="left")
        ttk.Label(wh, text="  ×  ").pack(side="left")
        ttk.Entry(wh, textvariable=self.v_rs_h, width=8).pack(side="left")
        ttk.Checkbutton(wh, text="保持宽高比", variable=self.v_rs_keep).pack(side="left", padx=10)
        self._grid_row(tab, row, "指定宽高", wh); row += 1
        self._grid_row(tab, row, "缩放百分比", ttk.Entry(tab, textvariable=self.v_rs_pct, width=18), "%"); row += 1
        self._grid_row(tab, row, "输出格式", ttk.Combobox(tab, textvariable=self.v_c_fmt, width=16,
                                                       state="readonly", values=output_formats())); row += 1
        self._grid_row(tab, row, "压缩质量",
                       self._slider_row(tab, self.v_c_quality, 1, 100, "质量", "(JPEG/WEBP，越小体积越小)")); row += 1
        png_box = ttk.Frame(tab)
        ttk.Checkbutton(png_box, text="PNG / GIF 有损瘦身（减少颜色数）",
                        variable=self.v_c_png_quant).pack(side="left")
        ttk.Entry(png_box, textvariable=self.v_c_png_colors, width=6).pack(side="left", padx=6)
        ttk.Label(png_box, text="色", foreground="#8a8f98").pack(side="left")
        self._grid_row(tab, row, "调色板", png_box); row += 1
        ttk.Label(tab, text="提示：需要「每张不超过 XX KB / MB」时，勾选底部 ☑ 指定输出文件大小上限，"
                            "程序会自动降质量、必要时缩放尺寸。",
                  foreground="#8a8f98", wraplength=760, justify="left").grid(
            row=row, column=1, sticky="w", pady=(10, 4))

    def _tab_convert(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ⇄ 格式转换  ")

        self.v_v_fmt = tk.StringVar(value="JPEG")
        self.v_v_quality = tk.IntVar(value=90)
        self.v_v_bg = tk.StringVar(value="#FFFFFF")

        row = 0
        self._grid_row(tab, row, "目标格式", ttk.Combobox(tab, textvariable=self.v_v_fmt, width=16,
                                                     state="readonly", values=output_formats()[1:])); row += 1
        self._grid_row(tab, row, "输出质量", self._slider_row(tab, self.v_v_quality, 1, 100, "质量")); row += 1
        bg_box = ttk.Frame(tab)
        ttk.Entry(bg_box, textvariable=self.v_v_bg, width=12).pack(side="left")
        ttk.Button(bg_box, text="选色…", width=7,
                   command=lambda: self._pick_color(self.v_v_bg)).pack(side="left", padx=6)
        self._grid_row(tab, row, "透明区域底色", bg_box, "转 JPG/BMP 时透明部分填充的颜色"); row += 1
        ttk.Label(tab, text="提示：PNG 转 JPEG 自动铺底色；动图转静态格式只取第一帧，转 GIF 则整段保留。",
                  foreground="#8a8f98").grid(row=row, column=1, sticky="w", pady=(10, 4))

    def _tab_crop(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ✂ 裁剪 · 旋转  ")

        self.v_crop_mode = tk.StringVar(value="不裁剪")
        self.v_crop_l = tk.StringVar(value="0")
        self.v_crop_t = tk.StringVar(value="0")
        self.v_crop_w = tk.StringVar(value="")
        self.v_crop_h = tk.StringVar(value="")
        self.v_crop_ratio = tk.StringVar(value="1:1")
        self.v_rot_mode = tk.StringVar(value="不旋转")
        self.v_rot_angle = tk.StringVar(value="0")
        self.v_flip = tk.StringVar(value="不翻转")
        self.v_border_w = tk.StringVar(value="0")
        self.v_border_c = tk.StringVar(value="#FFFFFF")

        row = 0
        self._grid_row(tab, row, "裁剪方式", ttk.Combobox(tab, textvariable=self.v_crop_mode, width=16,
                                                     state="readonly",
                                                     values=["不裁剪", "自定义像素", "居中比例"])); row += 1
        ltrb = ttk.Frame(tab)
        for text, var in (("左", self.v_crop_l), ("上", self.v_crop_t),
                          ("宽", self.v_crop_w), ("高", self.v_crop_h)):
            ttk.Label(ltrb, text=text).pack(side="left", padx=(0, 3))
            ttk.Entry(ltrb, textvariable=var, width=7).pack(side="left", padx=(0, 10))
        self._grid_row(tab, row, "裁剪区域", ltrb, "像素，宽/高留空表示到边缘"); row += 1
        self._grid_row(tab, row, "居中比例", ttk.Entry(tab, textvariable=self.v_crop_ratio, width=18),
                       "如 1:1 / 4:3 / 16:9"); row += 1
        self._grid_row(tab, row, "旋转", ttk.Combobox(tab, textvariable=self.v_rot_mode, width=18,
                                                    state="readonly",
                                                    values=["不旋转", "顺时针90°", "180°", "逆时针90°", "自定义角度"])); row += 1
        self._grid_row(tab, row, "自定义角度", ttk.Entry(tab, textvariable=self.v_rot_angle, width=18),
                       "度，顺时针为正"); row += 1
        self._grid_row(tab, row, "镜像翻转", ttk.Combobox(tab, textvariable=self.v_flip, width=18,
                                                      state="readonly",
                                                      values=["不翻转", "水平镜像", "垂直镜像"])); row += 1
        border_box = ttk.Frame(tab)
        ttk.Entry(border_box, textvariable=self.v_border_w, width=8).pack(side="left")
        ttk.Label(border_box, text="像素   颜色").pack(side="left", padx=8)
        ttk.Entry(border_box, textvariable=self.v_border_c, width=12).pack(side="left")
        ttk.Button(border_box, text="选色…", width=7,
                   command=lambda: self._pick_color(self.v_border_c)).pack(side="left", padx=6)
        self._grid_row(tab, row, "加边框", border_box); row += 1
        ttk.Label(tab, text="处理顺序：裁剪 → 旋转/镜像 → 缩放 → 边框 → 水印。",
                  foreground="#8a8f98").grid(row=row, column=1, sticky="w", pady=(10, 4))

    def _tab_watermark(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ▦ 水印  ")

        self.v_wm_type = tk.StringVar(value="文字水印")
        self.v_wm_text = tk.StringVar(value="© 袁鹏")
        self.v_wm_size = tk.StringVar(value="40")
        self.v_wm_color = tk.StringVar(value="#FFFFFF")
        self.v_wm_opacity = tk.IntVar(value=60)
        self.v_wm_pos = tk.StringVar(value="右下")
        self.v_wm_margin = tk.StringVar(value="20")
        self.v_wm_tile = tk.BooleanVar(value=False)
        self.v_wm_image = tk.StringVar(value="")
        self.v_wm_image_scale = tk.StringVar(value="20")

        row = 0
        self._grid_row(tab, row, "水印类型", ttk.Combobox(tab, textvariable=self.v_wm_type, width=16,
                                                    state="readonly",
                                                    values=["文字水印", "图片水印"])); row += 1
        self._grid_row(tab, row, "水印文字", ttk.Entry(tab, textvariable=self.v_wm_text, width=34)); row += 1
        font_box = ttk.Frame(tab)
        ttk.Entry(font_box, textvariable=self.v_wm_size, width=8).pack(side="left")
        ttk.Label(font_box, text="号   颜色").pack(side="left", padx=8)
        ttk.Entry(font_box, textvariable=self.v_wm_color, width=12).pack(side="left")
        ttk.Button(font_box, text="选色…", width=7,
                   command=lambda: self._pick_color(self.v_wm_color)).pack(side="left", padx=6)
        self._grid_row(tab, row, "字号 / 颜色", font_box); row += 1
        img_box = ttk.Frame(tab)
        ttk.Entry(img_box, textvariable=self.v_wm_image, width=30).pack(side="left")
        ttk.Button(img_box, text="选择…", width=7, command=self._pick_watermark_image).pack(side="left", padx=4)
        ttk.Label(img_box, text="缩放").pack(side="left", padx=(8, 2))
        ttk.Entry(img_box, textvariable=self.v_wm_image_scale, width=6).pack(side="left")
        ttk.Label(img_box, text="%").pack(side="left")
        self._grid_row(tab, row, "水印图片", img_box, "建议用带透明通道的 PNG"); row += 1
        self._grid_row(tab, row, "不透明度",
                       self._slider_row(tab, self.v_wm_opacity, 0, 100, "%")); row += 1
        self._grid_row(tab, row, "位置", ttk.Combobox(tab, textvariable=self.v_wm_pos, width=16,
                                                  state="readonly", values=POS_CHOICES)); row += 1
        self._grid_row(tab, row, "边距", ttk.Entry(tab, textvariable=self.v_wm_margin, width=18), "像素"); row += 1
        self._grid_row(tab, row, "平铺", ttk.Checkbutton(tab, text="铺满整张图（防搬运）",
                                                    variable=self.v_wm_tile)); row += 1

    def _tab_stitch(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ⌗ 拼接  ")

        self.v_st_dir = tk.StringVar(value="垂直拼接")
        self.v_st_gap = tk.StringVar(value="0")
        self.v_st_bg = tk.StringVar(value="#FFFFFF")
        self.v_st_unify = tk.BooleanVar(value=True)
        self.v_st_name = tk.StringVar(value="拼接图")

        row = 0
        self._grid_row(tab, row, "拼接方向", ttk.Combobox(tab, textvariable=self.v_st_dir, width=16,
                                                    state="readonly",
                                                    values=["垂直拼接", "水平拼接"])); row += 1
        self._grid_row(tab, row, "图片间距", ttk.Entry(tab, textvariable=self.v_st_gap, width=18), "像素"); row += 1
        bg_box = ttk.Frame(tab)
        ttk.Entry(bg_box, textvariable=self.v_st_bg, width=12).pack(side="left")
        ttk.Button(bg_box, text="选色…", width=7,
                   command=lambda: self._pick_color(self.v_st_bg)).pack(side="left", padx=6)
        self._grid_row(tab, row, "背景颜色", bg_box); row += 1
        self._grid_row(tab, row, "统一尺寸", ttk.Checkbutton(tab, text="按最大边等比缩放对齐",
                                                        variable=self.v_st_unify)); row += 1
        self._grid_row(tab, row, "输出文件名", ttk.Entry(tab, textvariable=self.v_st_name, width=24),
                       ".jpg 自动补后缀"); row += 1
        ttk.Label(tab, text="说明：拼接读取列表中的全部图片（勾选「只处理选中」则只拼选中的），输出一张长图。",
                  foreground="#8a8f98").grid(row=row, column=1, sticky="w", pady=(10, 4))

    def _tab_other(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  ⚙ 其他  ")

        self.v_o_action = tk.StringVar(value="批量重命名")
        self.v_o_prefix = tk.StringVar(value="IMG_")
        self.v_o_start = tk.StringVar(value="1")
        self.v_o_digits = tk.StringVar(value="3")
        self.v_o_keep = tk.BooleanVar(value=False)

        row = 0
        self._grid_row(tab, row, "操作类型", ttk.Combobox(tab, textvariable=self.v_o_action, width=22,
                                                    state="readonly",
                                                    values=["批量重命名", "清除 EXIF（另存）", "查看图片信息"])); row += 1
        rename_box = ttk.Frame(tab)
        ttk.Label(rename_box, text="前缀").pack(side="left")
        ttk.Entry(rename_box, textvariable=self.v_o_prefix, width=10).pack(side="left", padx=(3, 10))
        ttk.Label(rename_box, text="起始序号").pack(side="left")
        ttk.Entry(rename_box, textvariable=self.v_o_start, width=6).pack(side="left", padx=(3, 10))
        ttk.Label(rename_box, text="位数").pack(side="left")
        ttk.Entry(rename_box, textvariable=self.v_o_digits, width=5).pack(side="left", padx=(3, 10))
        ttk.Checkbutton(rename_box, text="保留原名", variable=self.v_o_keep).pack(side="left")
        self._grid_row(tab, row, "重命名", rename_box, "例如 IMG_001_原图名.jpg"); row += 1
        ttk.Label(tab, text="批量重命名只复制改名、不重新编码（画质零损失）；查看图片信息只写日志、不生成文件。",
                  foreground="#8a8f98").grid(row=row, column=1, sticky="w", pady=(10, 4))

    # ---------------------------------------------------------- 底部设置
    def _build_bottom(self):
        frame = ttk.LabelFrame(self.scroll_inner, text=" ⚙ 输出设置 ")
        frame.pack(fill="x", padx=10, pady=(0, 4))

        out_row = ttk.Frame(frame)
        out_row.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(out_row, text="输出目录").pack(side="left")
        ttk.Entry(out_row, textvariable=self._outdir_var(), width=56).pack(side="left", padx=6)
        ttk.Button(out_row, text="选择…", width=7, command=self._pick_outdir).pack(side="left")
        ttk.Button(out_row, text="打开 ▸", width=8, command=self._open_outdir).pack(side="left", padx=4)
        ttk.Label(out_row, text="后缀").pack(side="left", padx=(12, 2))
        ttk.Entry(out_row, textvariable=self._suffix_var(), width=8).pack(side="left")
        ttk.Label(out_row, text="可留空", foreground="#8a8f98").pack(side="left", padx=3)

        opt_row = ttk.Frame(frame)
        opt_row.pack(fill="x", padx=8, pady=2)
        ttk.Checkbutton(opt_row, text="去除 EXIF/元数据", variable=self._strip_var()).pack(side="left")
        ttk.Checkbutton(opt_row, text="按 EXIF 方向自动旋转", variable=self._orient_var()).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(opt_row, text="覆盖同名文件（否则自动加序号）",
                        variable=self._overwrite_var()).pack(side="left", padx=(16, 0))

        size_row = ttk.Frame(frame)
        size_row.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Checkbutton(size_row, text="☑ 指定输出文件大小上限", variable=self._limit_on_var(),
                        command=self._toggle_limit).pack(side="left")
        ttk.Label(size_row, text="每张不超过").pack(side="left", padx=(8, 3))
        self._limit_entry = ttk.Entry(size_row, textvariable=self._limit_var(), width=10)
        self._limit_entry.pack(side="left")
        self._limit_unit = ttk.Combobox(size_row, textvariable=self._limit_unit_var(), width=5,
                                        state="readonly", values=["KB", "MB"])
        self._limit_unit.pack(side="left", padx=4)
        ttk.Checkbutton(size_row, text="压不下去时自动缩小尺寸",
                        variable=self._limit_resize_var()).pack(side="left", padx=14)
        self._limit_hint = ttk.Label(size_row, text="不勾选 = 不限制体积", foreground="#8a8f98")
        self._limit_hint.pack(side="left")
        self._limit_var().trace_add("write", lambda *_: self._update_limit_hint())
        self._limit_unit_var().trace_add("write", lambda *_: self._update_limit_hint())

        action_row = ttk.Frame(frame)
        action_row.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_start = ttk.Button(action_row, text="▸ 开始处理", width=14, command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(action_row, text="■ 停止", width=8, state="disabled", command=self._stop)
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(action_row, text="◎ 预估体积", width=12, command=self._estimate).pack(side="left", padx=6)
        ttk.Button(action_row, text="⟳ 重置默认", width=11, command=self._reset_defaults).pack(side="left")
        self.progress = ttk.Progressbar(action_row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)
        self.progress_label = ttk.Label(action_row, text="0 / 0", foreground="#1f6feb", width=9)
        self.progress_label.pack(side="left")

    def _build_log(self):
        frame = ttk.LabelFrame(self.scroll_inner, text=" ▤ 处理日志 ")
        frame.pack(fill="both", expand=False, padx=10, pady=(0, 4))
        inner = ttk.Frame(frame)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        self.log = tk.Text(inner, height=6, wrap="none", font=("Consolas", 9))
        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set, state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.tag_config("error", foreground="#c0392b")
        self.log.tag_config("ok", foreground="#1e8449")
        self.log.tag_config("dim", foreground="#8a8f98")
        self.log.tag_config("warn", foreground="#b9770e")
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(0, weight=1)

    def _build_status(self):
        bar = tk.Frame(self.root, bg="#eef1f4")
        bar.pack(fill="x", side="bottom")
        self.status_label = tk.Label(bar, text="就绪 · 先添加图片，选择功能页后点「开始处理」",
                                     bg="#eef1f4", fg="#3a3f47", anchor="w",
                                     font=("Microsoft YaHei UI", 9))
        self.status_label.pack(side="left", padx=10, pady=3)
        tk.Label(bar, text="快捷键：Ctrl+O 添加 ｜ Ctrl+Shift+O 文件夹 ｜ Ctrl+Enter 处理 ｜ Ctrl+E 预估 ｜ Esc 停止",
                 bg="#eef1f4", fg="#8a8f98", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=16)
        self.status_right = tk.Label(bar, text="", bg="#eef1f4", fg="#1f6feb",
                                     font=("Microsoft YaHei UI", 9))
        self.status_right.pack(side="right", padx=10)

    def _bind_events(self):
        self.root.bind("<Control-o>", lambda _e: self.add_files())
        self.root.bind("<Control-O>", lambda _e: self.add_folder())
        self.root.bind("<Control-Return>", lambda _e: self._start())
        self.root.bind("<Escape>", lambda _e: self._stop())
        self.root.bind("<Control-e>", lambda _e: self._estimate())
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.tree.bind("<Double-1>", lambda _e: self._open_in_viewer())
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    # ---------------------------------------------------------- 变量
    def _outdir_var(self):
        if not hasattr(self, "v_outdir"):
            self.v_outdir = tk.StringVar(value="")
        return self.v_outdir

    def _suffix_var(self):
        if not hasattr(self, "v_suffix"):
            self.v_suffix = tk.StringVar(value="")
        return self.v_suffix

    def _strip_var(self):
        if not hasattr(self, "v_strip_exif"):
            self.v_strip_exif = tk.BooleanVar(value=True)
        return self.v_strip_exif

    def _orient_var(self):
        if not hasattr(self, "v_auto_orient"):
            self.v_auto_orient = tk.BooleanVar(value=True)
        return self.v_auto_orient

    def _overwrite_var(self):
        if not hasattr(self, "v_overwrite"):
            self.v_overwrite = tk.BooleanVar(value=False)
        return self.v_overwrite

    def _limit_on_var(self):
        if not hasattr(self, "v_limit_on"):
            self.v_limit_on = tk.BooleanVar(value=False)
        return self.v_limit_on

    def _limit_var(self):
        if not hasattr(self, "v_limit_value"):
            self.v_limit_value = tk.StringVar(value="300")
        return self.v_limit_value

    def _limit_unit_var(self):
        if not hasattr(self, "v_limit_unit"):
            self.v_limit_unit = tk.StringVar(value="KB")
        return self.v_limit_unit

    def _limit_resize_var(self):
        if not hasattr(self, "v_limit_resize"):
            self.v_limit_resize = tk.BooleanVar(value=True)
        return self.v_limit_resize

    # ---------------------------------------------------------- 小工具
    def _toggle_limit(self):
        enabled = self.v_limit_on.get()
        self._limit_entry.config(state="normal" if enabled else "disabled")
        self._limit_unit.config(state="readonly" if enabled else "disabled")
        self._update_limit_hint()
        self._refresh_limits_note()

    def _update_limit_hint(self):
        if not hasattr(self, "_limit_hint"):
            return
        if not self.v_limit_on.get():
            self._limit_hint.config(text="不勾选 = 不限制体积", foreground="#8a8f98")
        else:
            size = parse_size(self.v_limit_value.get(), self.v_limit_unit.get())
            if size <= 0:
                self._limit_hint.config(text="请输入有效数值，如 300 或 1.5", foreground="#c0392b")
            else:
                self._limit_hint.config(text="= 每张图 ≤ %s" % human_size(size), foreground="#1e8449")
        self._refresh_limits_note()

    def _refresh_limits_note(self):
        if not hasattr(self, "status_right"):
            return
        parts = ["共 %d 张" % len(self.files)]
        if self.v_limit_on.get():
            size = parse_size(self.v_limit_value.get(), self.v_limit_unit.get())
            if size > 0:
                parts.append("上限 ≤ %s" % human_size(size))
        self.status_right.config(text="  ｜  ".join(parts))

    def _set_status(self, text, color="#3a3f47"):
        self.status_label.config(text=text, fg=color)

    def _pick_color(self, var):
        rgb, _ = colorchooser.askcolor(color=var.get() or "#FFFFFF", title="选择颜色")
        if rgb:
            var.set("#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2])))

    def _pick_watermark_image(self):
        path = filedialog.askopenfilename(title="选择水印图片", filetypes=FILE_TYPES)
        if path:
            self.v_wm_image.set(path)

    def _pick_outdir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.v_outdir.set(path)

    def _open_outdir(self):
        path = self.v_outdir.get().strip()
        if path and os.path.isdir(path):
            os.startfile(path)
        else:
            messagebox.showinfo("提示", "请先设置一个存在的输出目录")

    # ---------------------------------------------------------- 文件管理
    def add_files(self):
        paths = filedialog.askopenfilenames(title="选择图片", filetypes=FILE_TYPES)
        self._extend_files(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择文件夹（含子文件夹）")
        if not folder:
            return
        found = []
        for root_dir, _, names in os.walk(folder):
            for name in sorted(names):
                if name.lower().endswith(IMAGE_EXTS):
                    found.append(os.path.join(root_dir, name))
        if not found:
            messagebox.showinfo("提示", "该文件夹里没有找到图片")
            return
        self._extend_files(found)

    def _extend_files(self, paths):
        added = []
        for path in paths:
            if path.lower().endswith(IMAGE_EXTS) and path not in self.files:
                self.files.append(path)
                added.append(path)
        if not added:
            return
        for path in added:
            name = os.path.basename(path)
            self.tree.insert("", "end", iid=path, text=name,
                             values=("读取中…", human_size(os.path.getsize(path)), "…"))
            self.tree.see(path)
        self.count_label.config(text="共 %d 张" % len(self.files))
        self._set_status("已添加 %d 张图片" % len(added), "#1e8449")
        if not self.v_outdir.get().strip():
            self.v_outdir.set(os.path.join(os.path.dirname(self.files[0]), "输出"))
        self._refresh_limits_note()
        self._scan_files(added)

    def _scan_files(self, paths):
        def work():
            for path in paths:
                try:
                    with Image.open(path) as im:
                        frames = getattr(im, "n_frames", 1)
                        self._emit("row", path,
                                   "%dx%d%s" % (im.width, im.height, " 动图%d帧" % frames if frames > 1 else ""),
                                   human_size(os.path.getsize(path)), im.format or "?")
                except Exception:
                    self._emit("row", path, "读取失败", "?", "?")
        threading.Thread(target=work, daemon=True).start()

    def remove_selected(self):
        selected = list(self.tree.selection())
        if not selected:
            return
        for path in selected:
            if path in self.files:
                self.files.remove(path)
            if self.tree.exists(path):
                self.tree.delete(path)
        self.count_label.config(text="共 %d 张" % len(self.files))
        self._refresh_limits_note()
        self.preview_label.config(image="", text="点击左侧图片查看预览")
        self._preview_img = None
        self.preview_info.config(text="—")

    def clear_files(self):
        self.files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.count_label.config(text="共 0 张")
        self._refresh_limits_note()
        self.preview_label.config(image="", text="点击左侧图片查看预览")
        self._preview_img = None
        self.preview_info.config(text="—")

    def _selected_files(self):
        selected = set(self.tree.selection())
        return [path for path in self.files if path in selected]

    def _on_select(self, _event=None):
        selected = self.tree.selection()
        if selected:
            self._show_preview(selected[0])

    def _show_preview(self, path):
        try:
            with Image.open(path) as im:
                im.seek(0)
                frame = ImageOps.exif_transpose(im) or im
                frame = frame.convert("RGBA") if frame.mode in ("P", "LA", "RGBA") else frame.convert("RGB")
                frames = getattr(im, "n_frames", 1)
                thumb = frame.copy()
                thumb.thumbnail((190, 150), Image.LANCZOS)
                info = ("%s\n%d × %d 像素 ｜ %s\n格式 %s%s"
                        % (os.path.basename(path), im.width, im.height,
                           human_size(os.path.getsize(path)), im.format or "?",
                           " ｜ 动图 %d 帧" % frames if frames > 1 else ""))
            if HAS_IMAGETK:
                self._preview_img = ImageTk.PhotoImage(thumb)
                self.preview_label.config(image=self._preview_img, text="")
            else:
                self.preview_label.config(image="", text=os.path.basename(path))
            self.preview_label.config(width=max(1, thumb.width), height=max(1, thumb.height))
            self.preview_info.config(text=info)
        except Exception as exc:
            self.preview_label.config(image="", text="无法预览")
            self._preview_img = None
            self.preview_info.config(text="读取失败：%s" % exc)

    def _popup_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _open_in_viewer(self):
        selected = self.tree.selection()
        if selected:
            try:
                os.startfile(selected[0])
            except OSError as exc:
                messagebox.showerror("错误", "无法打开：%s" % exc)

    def _reveal_in_explorer(self):
        selected = self.tree.selection()
        if selected:
            try:
                os.startfile(os.path.dirname(selected[0]))
            except OSError:
                pass

    def _copy_path(self):
        selected = self.tree.selection()
        if selected:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(selected))
            self._set_status("已复制 %d 条路径" % len(selected), "#1e8449")

    # ---------------------------------------------------------- 配置收集
    def _base_cfg(self):
        target = parse_size(self.v_limit_value.get(), self.v_limit_unit.get()) if self.v_limit_on.get() else 0
        return {
            "auto_orient": self.v_auto_orient.get(),
            "strip_exif": self.v_strip_exif.get(),
            "suffix": self.v_suffix.get().strip(),
            "out_dir": self.v_outdir.get().strip(),
            "overwrite": self.v_overwrite.get(),
            "rs_mode": "不缩放",
            "crop_mode": "不裁剪",
            "rot_mode": "不旋转",
            "wm_type": "文字水印",
            "border_width": "0",
            "target_bytes": target,
            "allow_resize": self.v_limit_resize.get(),
        }

    def _collect(self, tab_index):
        cfg = self._base_cfg()
        if tab_index == 0:
            cfg.update({
                "rs_mode": self.v_rs_mode.get(),
                "rs_long": self.v_rs_long.get(),
                "rs_w": self.v_rs_w.get(),
                "rs_h": self.v_rs_h.get(),
                "rs_pct": self.v_rs_pct.get(),
                "rs_keep": self.v_rs_keep.get(),
                "out_fmt": self.v_c_fmt.get(),
                "quality": self.v_c_quality.get(),
                "png_quant": self.v_c_png_quant.get(),
                "png_colors": _int(self.v_c_png_colors.get(), 128),
            })
        elif tab_index == 1:
            cfg.update({
                "out_fmt": self.v_v_fmt.get(),
                "quality": self.v_v_quality.get(),
                "bg": self.v_v_bg.get(),
            })
        elif tab_index == 2:
            cfg.update({
                "crop_mode": self.v_crop_mode.get(),
                "crop_l": self.v_crop_l.get(),
                "crop_t": self.v_crop_t.get(),
                "crop_w": self.v_crop_w.get(),
                "crop_h": self.v_crop_h.get(),
                "crop_ratio": self.v_crop_ratio.get(),
                "rot_mode": self.v_rot_mode.get(),
                "rot_angle": self.v_rot_angle.get(),
                "flip": self.v_flip.get(),
                "border_width": self.v_border_w.get(),
                "border_color": self.v_border_c.get(),
                "out_fmt": "保持原格式",
                "quality": 95,
            })
        elif tab_index == 3:
            cfg.update({
                "wm_type": self.v_wm_type.get(),
                "wm_text": self.v_wm_text.get(),
                "wm_size": self.v_wm_size.get(),
                "wm_color": self.v_wm_color.get(),
                "wm_opacity": self.v_wm_opacity.get(),
                "wm_pos": self.v_wm_pos.get(),
                "wm_margin": self.v_wm_margin.get(),
                "wm_tile": self.v_wm_tile.get(),
                "wm_image": self.v_wm_image.get(),
                "wm_image_scale": self.v_wm_image_scale.get(),
                "out_fmt": "保持原格式",
                "quality": 95,
            })
        elif tab_index == 4:
            cfg.update({
                "st_dir": self.v_st_dir.get(),
                "st_gap": self.v_st_gap.get(),
                "st_bg": self.v_st_bg.get(),
                "st_unify": self.v_st_unify.get(),
                "st_name": self.v_st_name.get(),
            })
        else:
            cfg.update({
                "action": self.v_o_action.get(),
                "prefix": self.v_o_prefix.get(),
                "start": _int(self.v_o_start.get(), 1),
                "digits": _int(self.v_o_digits.get(), 3),
                "keep_orig": self.v_o_keep.get(),
                "quality": 95,
            })
        return cfg

    # ---------------------------------------------------------- 启动处理
    def _start(self, only_selected=False):
        if self.busy:
            return
        tab_index = self.nb.index(self.nb.select())
        files = self._selected_files() if only_selected else list(self.files)
        cfg = self._collect(tab_index)

        if not files:
            messagebox.showwarning("提示", "请先添加要处理的图片" + ("，或选中若干张" if only_selected else ""))
            return
        if tab_index == 4 and len(files) < 2:
            messagebox.showwarning("提示", "拼接至少需要 2 张图片")
            return
        if self.v_limit_on.get() and not cfg["target_bytes"]:
            messagebox.showwarning("提示", "已勾选「指定输出文件大小上限」，请输入有效的数值（如 300 或 1.5）")
            return

        if not cfg["out_dir"]:
            guess = os.path.dirname(files[0]) if files else os.getcwd()
            cfg["out_dir"] = os.path.join(guess, "输出")
            self.v_outdir.set(cfg["out_dir"])
        try:
            os.makedirs(cfg["out_dir"], exist_ok=True)
        except OSError as exc:
            messagebox.showerror("错误", "无法创建输出目录：%s" % exc)
            return

        self.busy = True
        self.stop_flag.clear()
        self.start_time = datetime.now()
        self.progress.config(maximum=max(1, len(files)), value=0)
        self.progress_label.config(text="0 / %d" % len(files))
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

        tab_text = self.nb.tab(self.nb.select(), "text").strip()
        self._log("▸ 开始 %s ｜ %d 张图片%s" % (tab_text, len(files), "（仅选中）" if only_selected else ""), "dim")
        if cfg["target_bytes"]:
            self._log("  大小上限：每张 ≤ %s%s" % (
                human_size(cfg["target_bytes"]),
                "，压不下去时自动缩小尺寸" if cfg["allow_resize"] else "，不做自动缩放"), "dim")
        self._log("  输出目录：%s\n" % cfg["out_dir"], "dim")
        self._set_status("正在处理 %d 张图片……" % len(files), "#1f6feb")

        threading.Thread(target=self._worker, args=(tab_index, files, cfg), daemon=True).start()

    def _stop(self):
        if self.busy:
            self.stop_flag.set()
            self._log("已请求停止，当前文件处理完后中断……", "warn")

    def _estimate(self):
        if self.busy:
            return
        files = self._selected_files() or list(self.files)
        if not files:
            messagebox.showinfo("提示", "请先添加图片")
            return
        tab_index = self.nb.index(self.nb.select())
        if tab_index == 4:
            messagebox.showinfo("提示", "拼接页请直接点「开始处理」查看结果")
            return
        path = files[0]
        cfg = self._collect(tab_index)
        self._set_status("正在预估首张输出体积……", "#b9770e")

        def work():
            try:
                payload = load_payload(path, cfg)
                payload = render_payload(payload, cfg)
                fmt = resolve_format(cfg.get("out_fmt", "保持原格式"), path)
                if cfg.get("target_bytes"):
                    data, size, note = compress_to_target(payload, fmt, cfg)
                else:
                    data = encode_payload(payload, fmt, _default_param(fmt, cfg), cfg)
                    size, note = payload.size, ""
                self._emit("status", "◎ 预估：%s → %s ｜ 输出约 %s（%dx%d）%s" % (
                    os.path.basename(path), human_size(os.path.getsize(path)),
                    human_size(len(data)), size[0], size[1], ("　" + note) if note else ""))
            except Exception as exc:
                self._emit("status", "预估失败：%s" % exc)
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 工作线程
    def _worker(self, tab_index, files, cfg):
        total_before = total_after = done = missed = 0
        try:
            if tab_index == 4:
                self._emit("done", 1, 0, 0, self._stitch_all(files, cfg))
                return

            for index, path in enumerate(files, start=1):
                if self.stop_flag.is_set():
                    break
                name = os.path.basename(path)
                try:
                    if tab_index == 5 and cfg["action"] == "查看图片信息":
                        for line in describe(path):
                            self._log(line)
                        done += 1
                        continue

                    if tab_index == 5 and cfg["action"] == "批量重命名":
                        self._copy_renamed(path, cfg, index)
                        done += 1
                        continue

                    before = os.path.getsize(path)
                    payload = render_payload(load_payload(path, cfg), cfg)
                    animated = payload.animated

                    if tab_index == 5:                       # 清除 EXIF
                        fmt = resolve_format("保持原格式", path)
                        payload.exif = None
                        data = encode_payload(payload, fmt, 95, dict(cfg, quality=95))
                        note = ""
                    else:
                        fmt = resolve_format(cfg.get("out_fmt", "保持原格式"), path)
                        merged = dict(cfg)
                        if cfg.get("target_bytes"):
                            data, final_size, note = compress_to_target(payload, fmt, merged, self._log)
                        else:
                            data = encode_payload(payload, fmt, _default_param(fmt, cfg), merged)
                            note = ""
                        if animated and fmt != "GIF":
                            note = (note + "　动图只取第 1 帧").strip()

                    out_path = self._out_path(path, cfg, index, FMT_EXT.get(fmt, ".jpg"))
                    with open(out_path, "wb") as handle:
                        handle.write(data)

                    after = len(data)
                    total_before += before
                    total_after += after
                    done += 1
                    ratio = (1 - after / before) * 100 if before else 0
                    target = cfg.get("target_bytes") or 0
                    line = "%3d/%d  %s → %s   %s → %s (%+.0f%%)" % (
                        index, len(files), name, os.path.basename(out_path),
                        human_size(before), human_size(after), -ratio)
                    tag = "ok" if (after <= before and (not target or after <= target)) else None
                    if target:
                        met = after <= target
                        if not met:
                            missed += 1
                            tag = "warn"
                        line += "   目标 %s %s" % (human_size(target), "✓达标" if met else "✗未达标")
                    if note:
                        line += "   %s" % note
                    self._log(line, tag)
                except Exception as exc:  # 单张失败不影响其余
                    self._log("%3d/%d  %s  失败：%s" % (index, len(files), name, exc), "error")
                finally:
                    self._emit("progress", index)

            self._emit("done", done, total_before, total_after, missed)
        except Exception as exc:  # pragma: no cover
            self._log("处理中断：%s" % exc, "error")
            self._emit("done", done, total_before, total_after, missed)

    def _stitch_all(self, files, cfg):
        images = []
        for path in files:
            with Image.open(path) as im:
                im.seek(0)
                frame = ImageOps.exif_transpose(im) or im
                images.append(frame.convert("RGBA"))
                self._log("  已载入 %s (%dx%d)" % (os.path.basename(path), im.width, im.height))
        canvas = stitch_images(images, cfg)
        name = (cfg.get("st_name") or "拼接图").strip()
        out_path = self._path_with_policy(os.path.join(cfg["out_dir"], name + ".jpg"), cfg)
        if cfg.get("target_bytes"):
            data, _, note = compress_to_target(Payload([canvas.convert("RGBA")]), "JPEG",
                                               dict(cfg, quality=92), self._log)
            with open(out_path, "wb") as handle:
                handle.write(data)
            met = len(data) <= cfg["target_bytes"]
            self._log("⌗ 拼接完成：%dx%d → %s (%s)   目标 %s %s %s"
                      % (canvas.width, canvas.height, out_path, human_size(len(data)),
                         human_size(cfg["target_bytes"]), "✓达标" if met else "✗未达标", note), "ok")
            return 0 if met else 1
        canvas.save(out_path, format="JPEG", quality=92, optimize=True)
        self._log("⌗ 拼接完成：%dx%d → %s (%s)"
                  % (canvas.width, canvas.height, out_path, human_size(os.path.getsize(out_path))), "ok")
        return 0

    def _copy_renamed(self, path, cfg, index):
        digits = max(1, cfg.get("digits", 3))
        serial = cfg.get("start", 1) + index - 1
        base = os.path.splitext(os.path.basename(path))[0]
        new_name = "%s%0*d" % (cfg.get("prefix", ""), digits, serial)
        if cfg.get("keep_orig"):
            new_name += "_" + base
        new_name += os.path.splitext(path)[1]
        out_path = self._path_with_policy(os.path.join(cfg["out_dir"], new_name), cfg)
        if os.path.abspath(out_path) == os.path.abspath(path):
            self._log("%3d  %s  与源文件同名，已跳过" % (index, base), "dim")
            return
        shutil.copy2(path, out_path)
        self._log("%3d  %s → %s" % (index, os.path.basename(path), os.path.basename(out_path)), "ok")

    def _out_path(self, src_path, cfg, index, ext):
        base = os.path.splitext(os.path.basename(src_path))[0]
        suffix = cfg.get("suffix", "")
        out_path = os.path.join(cfg["out_dir"], "%s%s%s" % (base, suffix, ext))
        if os.path.abspath(out_path) == os.path.abspath(src_path):
            out_path = os.path.join(cfg["out_dir"], "%s%s_out%s" % (base, suffix, ext))
        return self._path_with_policy(out_path, cfg)

    def _path_with_policy(self, path, cfg):
        if cfg.get("overwrite"):
            return path
        return unique_path(path)

    # ---------------------------------------------------------- 队列与日志
    def _emit(self, kind, *args):
        self.msg_queue.put((kind, args))

    def _log(self, text, tag=None):
        self.msg_queue.put(("log", (text + "\n", tag)))

    def _poll(self):
        try:
            while True:
                kind, args = self.msg_queue.get_nowait()
                if kind == "log":
                    self._write_log(*args)
                elif kind == "progress":
                    self.progress.config(value=args[0])
                    self.progress_label.config(text="%d / %d" % (args[0], self.progress.cget("maximum")))
                elif kind == "row":
                    path, size_text, bytes_text, fmt = args
                    if self.tree.exists(path):
                        self.tree.item(path, values=(size_text, bytes_text, fmt))
                elif kind == "status":
                    self._set_status(args[0], "#1f6feb")
                elif kind == "done":
                    self._finish(*args)
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _write_log(self, text, tag=None):
        self.log.config(state="normal")
        self.log.insert("end", text, tag or "")
        self.log.see("end")
        self.log.config(state="disabled")

    def _finish(self, done, before, after, missed=0):
        self.busy = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        spent = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        stamp = datetime.now().strftime("%H:%M:%S")
        if before and after:
            self._log("\n[%s] 完成：成功 %d 个文件 ｜ 体积 %s → %s（节省 %.0f%%）｜ 用时 %.1fs"
                      % (stamp, done, human_size(before), human_size(after),
                         (1 - after / float(before)) * 100, spent), "ok")
        else:
            self._log("\n[%s] 完成：成功 %d 个文件 ｜ 用时 %.1fs" % (stamp, done, spent), "ok")
        if missed:
            self._log("⚠ 有 %d 张未压到目标大小，可勾选「压不下去时自动缩小尺寸」或放宽限制。" % missed, "warn")
            self._set_status("完成：%d 个文件，%d 张未达目标大小" % (done, missed), "#b9770e")
        else:
            if done and self.v_limit_on.get():
                self._log("✓ 全部文件均满足大小要求。", "ok")
            self._set_status("完成：%d 个文件，用时 %.1fs" % (done, spent), "#1e8449")
        self._save_settings()

    # ---------------------------------------------------------- 设置持久化
    def _all_vars(self):
        return {name: value for name, value in vars(self).items()
                if name.startswith("v_") and isinstance(value, tk.Variable)}

    def _save_settings(self):
        try:
            data = {name: var.get() for name, var in self._all_vars().items()}
            with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except (OSError, TypeError, tk.TclError):
            pass

    def _load_settings(self):
        if not os.path.exists(SETTINGS_PATH):
            return
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        variables = self._all_vars()
        for name, value in data.items():
            if name in variables:
                try:
                    variables[name].set(value)
                except (tk.TclError, TypeError):
                    continue

    def _reset_defaults(self):
        for name, var in self._all_vars().items():
            defaults = DEFAULT_SETTINGS.get(name)
            if defaults is not None:
                try:
                    var.set(defaults)
                except tk.TclError:
                    continue
        self._toggle_limit()
        self._set_status("已恢复默认设置", "#1e8449")

    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno("正在处理", "还有文件在处理中，确定要退出吗？"):
                return
            self.stop_flag.set()
        self._save_settings()
        self.root.destroy()


DEFAULT_SETTINGS = {
    "v_rs_mode": "长边限制", "v_rs_long": "1920", "v_rs_w": "1920", "v_rs_h": "1080",
    "v_rs_pct": "70", "v_rs_keep": True, "v_c_fmt": "保持原格式", "v_c_quality": 85,
    "v_c_png_quant": False, "v_c_png_colors": "128",
    "v_v_fmt": "JPEG", "v_v_quality": 90, "v_v_bg": "#FFFFFF",
    "v_crop_mode": "不裁剪", "v_crop_l": "0", "v_crop_t": "0", "v_crop_w": "", "v_crop_h": "",
    "v_crop_ratio": "1:1", "v_rot_mode": "不旋转", "v_rot_angle": "0", "v_flip": "不翻转",
    "v_border_w": "0", "v_border_c": "#FFFFFF",
    "v_wm_type": "文字水印", "v_wm_text": "© 袁鹏", "v_wm_size": "40", "v_wm_color": "#FFFFFF",
    "v_wm_opacity": 60, "v_wm_pos": "右下", "v_wm_margin": "20", "v_wm_tile": False,
    "v_wm_image": "", "v_wm_image_scale": "20",
    "v_st_dir": "垂直拼接", "v_st_gap": "0", "v_st_bg": "#FFFFFF", "v_st_unify": True, "v_st_name": "拼接图",
    "v_o_action": "批量重命名", "v_o_prefix": "IMG_", "v_o_start": "1", "v_o_digits": "3", "v_o_keep": False,
    "v_suffix": "", "v_strip_exif": True, "v_auto_orient": True, "v_overwrite": False,
    "v_limit_on": False, "v_limit_value": "300", "v_limit_unit": "KB", "v_limit_resize": True,
}


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("TNotebook.Tab", padding=(12, 6))
    except tk.TclError:
        pass
    ImageToolbox(root)
    root.mainloop()


if __name__ == "__main__":
    main()
