"""
一次性脚本：生成 icon.ico（exe/打包用，多尺寸）与 icon.png（通知用，圆形 app logo）。
图标绘制统一走 iconart.render，与托盘 tray._make_icon 视觉一致。
用法：python make_icon.py
"""
import iconart


def main():
    ico_sizes = [256, 128, 64, 48, 32, 16]
    base = iconart.render(256)
    base.save('icon.ico', format='ICO', sizes=[(s, s) for s in ico_sizes])
    # 通知图标：256 PNG（Windows Toast appLogoOverride 用 PNG，.ico 不渲染）
    base.save('icon.png', format='PNG')
    print('已生成 icon.ico（尺寸', ico_sizes, '）与 icon.png(256)')


if __name__ == '__main__':
    main()
