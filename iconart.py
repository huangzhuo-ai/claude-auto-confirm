"""
图标绘制（共享）：托盘图标、exe 图标(.ico)、通知图标(.png) 统一从这里出，保证视觉一致。

比旧版（纯色圆 + 折线）精致：
- 垂直渐变紫色底（亮紫 → 深紫），更有质感
- 柔和高光弧，模拟光泽
- 抗锯齿对勾（4× 超采样后缩小），边缘平滑
- 暂停态用灰色渐变 + 暂停竖条
所有绘制按基准尺寸等比缩放，任意尺寸都清晰。
"""
from PIL import Image, ImageDraw

# 品牌色：亮紫→深紫渐变（与原 (138,92,246) 同色系，做出层次）
_PURPLE_TOP = (164, 120, 255)
_PURPLE_BOT = (120, 72, 230)
_GRAY_TOP = (150, 150, 156)
_GRAY_BOT = (110, 110, 116)
_SS = 4  # 超采样倍数（抗锯齿）


def _vgradient(size: int, top: tuple, bot: tuple) -> Image.Image:
    """生成 size×size 的垂直渐变图（RGBA，不透明）。"""
    grad = Image.new('RGB', (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return grad.resize((size, size)).convert('RGBA')


def render(size: int = 256, paused: bool = False) -> Image.Image:
    """渲染一个 size×size 的图标（RGBA，透明背景外接圆）。"""
    S = size * _SS
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))

    # 1) 圆底：用渐变填充 + 圆形蒙版
    top, bot = (_GRAY_TOP, _GRAY_BOT) if paused else (_PURPLE_TOP, _PURPLE_BOT)
    grad = _vgradient(S, top, bot)
    mask = Image.new('L', (S, S), 0)
    md = ImageDraw.Draw(mask)
    pad = int(S * 0.04)
    md.ellipse([pad, pad, S - pad, S - pad], fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # 2) 顶部柔和高光弧（白色半透明），模拟光泽
    hl = int(S * 0.10)
    d.arc([pad + hl, pad + hl, S - pad - hl, S - pad - hl],
          start=200, end=340, fill=(255, 255, 255, 70), width=max(2, int(S * 0.02)))

    # 3) 中心符号
    if paused:
        # 暂停：两根圆头竖条
        bw = int(S * 0.09)
        gap = int(S * 0.08)
        h0, h1 = int(S * 0.34), int(S * 0.66)
        cx = S // 2
        for dx in (-gap - bw // 2, gap + bw // 2):
            x = cx + dx
            d.rounded_rectangle([x - bw // 2, h0, x + bw // 2, h1],
                                radius=bw // 2, fill=(255, 255, 255, 255))
    else:
        # 对勾：圆头折线
        w = max(3, int(S * 0.085))
        pts = [(int(S * 0.30), int(S * 0.53)),
               (int(S * 0.44), int(S * 0.68)),
               (int(S * 0.72), int(S * 0.34))]
        d.line(pts, fill=(255, 255, 255, 255), width=w, joint='curve')
        # 折线端点补圆头，避免直角
        for p in (pts[0], pts[2]):
            d.ellipse([p[0] - w // 2, p[1] - w // 2, p[0] + w // 2, p[1] + w // 2],
                      fill=(255, 255, 255, 255))

    # 超采样缩回目标尺寸（抗锯齿）
    return img.resize((size, size), Image.LANCZOS)
