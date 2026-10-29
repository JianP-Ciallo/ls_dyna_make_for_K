from __future__ import annotations

from pathlib import Path

try:
    from .work_paths import generated_path
except ImportError:  # Direct script invocation.
    from work_paths import generated_path
from PIL import Image, ImageDraw, ImageFont


OUT_DIR = generated_path("generated_softdoc_figures")
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
BOLD_FONT_PATH = Path(r"C:\Windows\Fonts\msyhbd.ttc")

INK = "#24313B"
BLUE = "#236B8E"
LIGHT_BLUE = "#EAF3F7"
LIGHT_TEAL = "#EAF5F2"
LIGHT_GRAY = "#F4F6F7"
LIGHT_RED = "#FBEDED"
RED = "#A44949"
GREEN = "#3D7D6B"
LINE = "#33434D"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = BOLD_FONT_PATH if bold and BOLD_FONT_PATH.exists() else FONT_PATH
    return ImageFont.truetype(str(path), size=size)


def text_box(draw: ImageDraw.ImageDraw, xy, text: str, *, size=34, bold=False, fill=INK, anchor="mm"):
    draw.multiline_text(
        xy,
        text,
        font=font(size, bold),
        fill=fill,
        anchor=anchor,
        align="center",
        spacing=9,
    )


def rounded_box(draw, box, text, *, fill=LIGHT_BLUE, outline=LINE, width=3, size=32, bold=False):
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=width)
    x1, y1, x2, y2 = box
    text_box(draw, ((x1 + x2) / 2, (y1 + y2) / 2), text, size=size, bold=bold)


def diamond(draw, center, width, height, text, *, fill=LIGHT_GRAY, outline=LINE):
    x, y = center
    points = [(x, y - height / 2), (x + width / 2, y), (x, y + height / 2), (x - width / 2, y)]
    draw.polygon(points, fill=fill, outline=outline)
    draw.line(points + [points[0]], fill=outline, width=3, joint="curve")
    text_box(draw, center, text, size=31, bold=True)


def arrow(draw, start, end, *, color=LINE, width=4, label=None, label_offset=(0, 0)):
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = (x2, y2)
    base = (x2 - ux * 24, y2 - uy * 24)
    left = (base[0] + px * 10, base[1] + py * 10)
    right = (base[0] - px * 10, base[1] - py * 10)
    draw.polygon([tip, left, right], fill=color)
    if label:
        mx = (x1 + x2) / 2 + label_offset[0]
        my = (y1 + y2) / 2 + label_offset[1]
        text_box(draw, (mx, my), label, size=27, bold=True, fill=color)


def overall_flow() -> Path:
    image = Image.new("RGB", (1800, 1560), "white")
    draw = ImageDraw.Draw(image)
    text_box(draw, (900, 55), "智能毁伤评估总体流程", size=44, bold=True, fill=BLUE)

    boxes = {
        "register": (580, 110, 1220, 220),
        "identity": (580, 270, 1220, 390),
        "semantic": (580, 610, 1220, 720),
        "metrics": (580, 770, 1220, 890),
        "grading": (580, 1110, 1220, 1225),
        "aggregate": (580, 1275, 1220, 1385),
        "report": (580, 1430, 1220, 1535),
    }
    rounded_box(draw, boxes["register"], "登记求解结果\nmodel.k、model.json及结果文件", fill=LIGHT_BLUE, bold=True)
    rounded_box(draw, boxes["identity"], "结果来源与身份核验\n模型哈希、运行ID、文件连续性和证据摘要", fill=LIGHT_BLUE)
    diamond(draw, (900, 500), 410, 150, "求解质量及\n对象响应完整？")
    rounded_box(draw, boxes["semantic"], "语义对象绑定\n设施－构件－部件－响应对象", fill=LIGHT_TEAL)
    rounded_box(draw, boxes["metrics"], "物理指标自动提取\n压力、冲量、应力、位移、材料损伤和到达时间", fill=LIGHT_TEAL)
    diamond(draw, (900, 1000), 410, 150, "适用毁伤判据\n已复核并绑定？")
    rounded_box(draw, boxes["grading"], "对象级毁伤分级\n低／关注／较高／严重", fill="#EEF2FA", bold=True)
    rounded_box(draw, boxes["aggregate"], "设施级汇总与异常识别\n关键部位、最高等级、缺失响应和矛盾指标", fill="#EEF2FA")
    rounded_box(draw, boxes["report"], "生成智能评估报告\nJSON／HTML、判定依据和不可变证据指纹", fill=LIGHT_BLUE, bold=True)

    rounded_box(draw, (1320, 430, 1740, 570), "阻断评估\n输出“无法评估”\n保留缺失与异常证据", fill=LIGHT_RED, outline=RED, size=29)
    rounded_box(draw, (1320, 930, 1740, 1070), "等待判据或人工复核\n不得使用演示阈值\n替代工程判据", fill=LIGHT_RED, outline=RED, size=29)

    arrow(draw, (900, 220), (900, 270))
    arrow(draw, (900, 390), (900, 425))
    arrow(draw, (900, 575), (900, 610), color=GREEN, label="是", label_offset=(35, 0))
    arrow(draw, (1105, 500), (1320, 500), color=RED, label="否", label_offset=(0, -28))
    arrow(draw, (900, 720), (900, 770))
    arrow(draw, (900, 890), (900, 925))
    arrow(draw, (900, 1075), (900, 1110), color=GREEN, label="是", label_offset=(35, 0))
    arrow(draw, (1105, 1000), (1320, 1000), color=RED, label="否", label_offset=(0, -28))
    arrow(draw, (900, 1225), (900, 1275))
    arrow(draw, (900, 1385), (900, 1430))

    path = OUT_DIR / "figure_10_1_intelligent_damage_flow.png"
    image.save(path, dpi=(220, 220))
    return path


def grading_logic() -> Path:
    image = Image.new("RGB", (1800, 1120), "white")
    draw = ImageDraw.Draw(image)
    text_box(draw, (900, 55), "对象级毁伤分级与设施级汇总逻辑", size=44, bold=True, fill=BLUE)

    text_box(draw, (265, 125), "评估输入", size=34, bold=True, fill=BLUE)
    rounded_box(draw, (70, 175, 460, 300), "设施语义对象\n类别、构件、材料、部件编号", fill=LIGHT_BLUE, size=29)
    rounded_box(draw, (70, 345, 460, 500), "对象级物理指标\n压力／冲量／应力／位移\n损伤指标／到达时间", fill=LIGHT_TEAL, size=29)
    rounded_box(draw, (70, 545, 460, 700), "毁伤判据档案\n来源、复核状态、适用范围\n模型及材料契约绑定", fill=LIGHT_GRAY, size=29)

    rounded_box(draw, (610, 260, 1030, 430), "逐指标阈值比较\n关注＜较高＜严重\n保留触发指标与实际值", fill="#EEF2FA", size=31, bold=True)
    rounded_box(draw, (610, 510, 1030, 660), "证据与适用性检查\n缺失、噪声、时程不足\n判据不匹配", fill=LIGHT_RED, outline=RED, size=29)

    rounded_box(draw, (1160, 190, 1570, 350), "对象级毁伤风险\n按最不利适用指标确定\n低／关注／较高／严重", fill=LIGHT_TEAL, size=30, bold=True)
    rounded_box(draw, (1160, 445, 1570, 600), "无法评估\n证据、指标或判据不足时\n禁止生成确定性等级", fill=LIGHT_RED, outline=RED, size=29)

    rounded_box(draw, (1030, 770, 1430, 920), "设施级汇总\n关键部位、最高等级\n受影响对象数量和部件映射", fill=LIGHT_BLUE, size=29, bold=True)
    rounded_box(draw, (1480, 770, 1750, 920), "异常识别\n缺失／冲突／异常位移", fill=LIGHT_GRAY, size=28)
    rounded_box(draw, (1030, 970, 1750, 1080), "输出：毁伤等级、判定依据、阈值来源、工程提示及证据摘要", fill="#EEF2FA", size=29, bold=True)

    arrow(draw, (460, 238), (610, 310))
    arrow(draw, (460, 422), (610, 345))
    arrow(draw, (460, 622), (610, 385))
    arrow(draw, (1030, 345), (1160, 270), color=GREEN, label="通过", label_offset=(0, -25))
    arrow(draw, (820, 430), (820, 510))
    arrow(draw, (1030, 585), (1160, 522), color=RED, label="不通过", label_offset=(0, -25))
    arrow(draw, (1365, 350), (1230, 770))
    arrow(draw, (1570, 270), (1615, 770))
    arrow(draw, (1230, 920), (1230, 970))
    arrow(draw, (1615, 920), (1615, 970))

    text_box(draw, (310, 820), "物理依据", size=32, bold=True, fill=GREEN)
    text_box(draw, (310, 895), "模型对象  →  求解响应  →  受控判据  →  分级结论", size=30, bold=True, fill=INK)
    draw.line([(90, 955), (530, 955)], fill=GREEN, width=5)
    text_box(draw, (310, 1015), "每一级结论均保留来源和证据，不由语言模型直接决定", size=27, fill=INK)

    path = OUT_DIR / "figure_10_2_damage_grading_logic.png"
    image.save(path, dpi=(220, 220))
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (overall_flow(), grading_logic()):
        print(path)


if __name__ == "__main__":
    main()
