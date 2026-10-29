from pathlib import Path

try:
    from .work_paths import generated_path
except ImportError:  # Direct script invocation.
    from work_paths import generated_path

from PIL import Image, ImageDraw, ImageFont


OUT = generated_path("generated_softdoc_figures", "figure_10_2_damage_grading_logic.png")
FONT_REGULAR = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def centered_text(draw, box, text, size=28, fill="#18323a", bold=False, spacing=8):
    x1, y1, x2, y2 = box
    fnt = font(size, bold)
    bounds = draw.multiline_textbbox((0, 0), text, font=fnt, spacing=spacing, align="center")
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    draw.multiline_text(
        ((x1 + x2 - w) / 2, (y1 + y2 - h) / 2 - bounds[1]),
        text,
        font=fnt,
        fill=fill,
        spacing=spacing,
        align="center",
    )


def rounded_box(draw, box, text, fill, outline="#3c5962", width=3, size=28, bold=False):
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=width)
    centered_text(draw, box, text, size=size, bold=bold)


def arrow(draw, start, end, fill="#49636b", width=5, head=16):
    draw.line((start, end), fill=fill, width=width)
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    points = [
        (x2, y2),
        (x2 - head * ux + head * 0.55 * px, y2 - head * uy + head * 0.55 * py),
        (x2 - head * ux - head * 0.55 * px, y2 - head * uy - head * 0.55 * py),
    ]
    draw.polygon(points, fill=fill)


def main():
    img = Image.new("RGB", (1800, 1160), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.text((70, 45), "对象级毁伤分级与设施级汇总逻辑", font=font(46, True), fill="#17363d")
    draw.line((70, 112, 1730, 112), fill="#1f6975", width=5)

    rounded_box(draw, (70, 180, 330, 340), "设施语义对象\n构件/区域/功能单元", "#e8f4f6", size=27)
    rounded_box(draw, (410, 180, 675, 340), "物理响应指标\n峰值位移、应变、\n冲量、失效比例等", "#eef3fa", size=26)
    rounded_box(draw, (755, 180, 1020, 340), "受控阈值档案\n对象类型、材料、\n关注/较高/严重阈值", "#f4f0fa", size=25)
    rounded_box(draw, (1100, 180, 1370, 340), "对象级分级\n按最严重有效指标\n确定综合等级", "#fff4df", size=26)
    rounded_box(draw, (1450, 180, 1730, 340), "证据记录\n指标值、阈值版本、\n来源文件与时间戳", "#eef7eb", size=25)

    for x1, x2 in [(330, 410), (675, 755), (1020, 1100), (1370, 1450)]:
        arrow(draw, (x1, 260), (x2, 260))

    draw.text((78, 405), "四级毁伤判定", font=font(31, True), fill="#244b54")
    grades = [
        ((70, 465, 415, 620), "I级：基本完好\n指标低于关注阈值", "#e9f6ec", "#2b7541"),
        ((505, 465, 850, 620), "II级：轻度毁伤\n达到关注阈值", "#fff8db", "#8b6d00"),
        ((940, 465, 1285, 620), "III级：中度毁伤\n达到较高阈值", "#ffeddc", "#a95712"),
        ((1375, 465, 1730, 620), "IV级：严重毁伤\n达到严重阈值", "#fde8e7", "#a22d2d"),
    ]
    for box, label, fill, outline in grades:
        rounded_box(draw, box, label, fill, outline=outline, width=4, size=27, bold=True)
        arrow(draw, (1235, 340), ((box[0] + box[2]) / 2, box[1]), fill="#647981", width=3, head=12)

    rounded_box(
        draw,
        (70, 735, 885, 1040),
        "物理依据链\n\n设施语义对象 → 求解响应 → 受控判据 → 分级结论\n\n每一级结论均保留指标来源、阈值版本和计算证据；\n大语言模型仅用于结果解释，不直接改变物理分级结论。",
        "#eaf5f6",
        outline="#2c7680",
        width=4,
        size=25,
        bold=False,
    )

    rounded_box(draw, (980, 735, 1345, 885), "设施级汇总\n按对象权重与最严重等级\n形成总体毁伤等级", "#e9f2fb", size=25)
    rounded_box(draw, (1420, 735, 1730, 885), "异常识别\n证据缺失、指标冲突、\n阈值越界与响应异常", "#f9eeee", size=24)
    arrow(draw, (1285, 620), (1160, 735), fill="#647981", width=4)
    arrow(draw, (1285, 620), (1575, 735), fill="#647981", width=4)
    arrow(draw, (1345, 810), (1420, 810), fill="#647981", width=4)

    rounded_box(
        draw,
        (980, 950, 1730, 1085),
        "结构化输出：总体等级、对象清单、关键指标\n异常项、判据说明与证据索引",
        "#edf6ef",
        outline="#3d7950",
        width=4,
        size=25,
        bold=True,
    )
    arrow(draw, (1160, 885), (1160, 950), fill="#647981", width=4)
    arrow(draw, (1575, 885), (1575, 950), fill="#647981", width=4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, dpi=(220, 220))
    print(OUT)


if __name__ == "__main__":
    main()
