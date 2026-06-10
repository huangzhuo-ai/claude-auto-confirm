"""
一次性脚本：生成 icon.ico（紫底白对勾，与托盘图标 tray._make_icon 视觉统一）。
用法：python make_icon.py  →  产出 icon.ico（多尺寸，供 PyInstaller 打包引用）。
"""
from PIL import Image, ImageDraw


def _draw(size: int) -> Image.Image:
    """按比例画一个 size×size 的紫底白对勾图标。"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0  # 以 64 为基准等比缩放
    d.ellipse([4 * s, 4 * s, 60 * s, 60 * s], fill=(138, 92, 246, 255))
    d.line([(20 * s, 34 * s), (29 * s, 44 * s), (46 * s, 22 * s)],
           fill=(255, 255, 255, 255), width=max(2, int(6 * s)))
    return img


def main():
    sizes = [256, 128, 64, 48, 32, 16]
    base = _draw(256)
    base.save('icon.ico', format='ICO',
              sizes=[(s, s) for s in sizes])
    print('已生成 icon.ico，尺寸:', sizes)


if __name__ == '__main__':
    main()
