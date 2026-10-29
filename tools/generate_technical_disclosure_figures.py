from __future__ import annotations

import math
from pathlib import Path

try:
    from .work_paths import generated_path
except ImportError:  # Direct script invocation.
    from work_paths import generated_path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = generated_path("technical_disclosure_work", "figures")
WIDTH = 2400
HEIGHT = 1500
INK = "#111111"
MID = "#555555"
LIGHT = "#F0F2F3"
PALE = "#FAFAFA"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


TITLE = font(50, True)
HEAD = font(34, True)
BODY = font(28)
SMALL = font(24)


def canvas(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    draw.text((80, 54), title, fill=INK, font=TITLE)
    draw.line((80, 126, WIDTH - 80, 126), fill=INK, width=4)
    return image, draw


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textbbox((0, 0), candidate, font=fnt)[2] > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont = BODY,
    fill: str = INK,
    pad: int = 24,
) -> None:
    x1, y1, x2, y2 = box
    lines = wrap(draw, text, fnt, x2 - x1 - 2 * pad)
    line_height = int(fnt.size * 1.38)
    total = line_height * len(lines)
    y = y1 + max(0, (y2 - y1 - total) // 2)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=fnt)
        width = bbox[2] - bbox[0]
        draw.text((x1 + (x2 - x1 - width) / 2, y), line, fill=fill, font=fnt)
        y += line_height


def box(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    text: str,
    *,
    fill: str = PALE,
    width: int = 4,
    fnt: ImageFont.FreeTypeFont = BODY,
    radius: int = 12,
) -> None:
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=INK, width=width)
    centered_text(draw, rect, text, fnt)


def diamond(draw: ImageDraw.ImageDraw, center: tuple[int, int], size: tuple[int, int], text: str) -> None:
    cx, cy = center
    w, h = size
    points = [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]
    draw.polygon(points, fill=PALE, outline=INK)
    draw.line(points + [points[0]], fill=INK, width=4, joint="curve")
    centered_text(draw, (cx - w // 3, cy - h // 4, cx + w // 3, cy + h // 4), text, SMALL)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    label: str | None = None,
    width: int = 4,
) -> None:
    draw.line((start, end), fill=INK, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 22
    spread = math.pi / 7
    p1 = (end[0] - length * math.cos(angle - spread), end[1] - length * math.sin(angle - spread))
    p2 = (end[0] - length * math.cos(angle + spread), end[1] - length * math.sin(angle + spread))
    draw.polygon([end, p1, p2], fill=INK)
    if label:
        mx = (start[0] + end[0]) // 2
        my = (start[1] + end[1]) // 2
        bbox = draw.textbbox((0, 0), label, font=SMALL)
        draw.rectangle((mx - (bbox[2] - bbox[0]) // 2 - 8, my - 20, mx + (bbox[2] - bbox[0]) // 2 + 8, my + 20), fill=WHITE)
        draw.text((mx - (bbox[2] - bbox[0]) / 2, my - 17), label, fill=INK, font=SMALL)


def poly_arrow(draw: ImageDraw.ImageDraw, points: Iterable[tuple[int, int]], label: str | None = None) -> None:
    pts = list(points)
    for a, b in zip(pts, pts[1:]):
        draw.line((a, b), fill=INK, width=4)
    if len(pts) >= 2:
        arrow(draw, pts[-2], pts[-1], label=label)


def save(image: Image.Image, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_DIR / name, dpi=(220, 220), optimize=True)


def figure_1() -> None:
    image, draw = canvas("面向关键基础设施爆炸毁伤的整体处理流程")
    labels = [
        "S101\n接收项目、工况和评估目标",
        "S102\n受控解析并统一单位",
        "S103\n构建场景中间表示",
        "S104\n匹配设施模板与能力声明",
        "S105\n编译结构、材料和网格",
        "S106\n配置TNT、ALE域与FSI",
        "S107\n确定性生成K文件包",
        "S108\n分级校验与就绪门禁",
        "S109\n提取对象级物理响应",
        "S110\n毁伤分级与证据归档",
    ]
    rects: list[tuple[int, int, int, int]] = []
    for row in range(2):
        for col in range(5):
            x1 = 90 + col * 458
            y1 = 230 + row * 650
            rects.append((x1, y1, x1 + 360, y1 + 210))
    for rect, label in zip(rects, labels):
        box(draw, rect, label, fill=LIGHT if "S10" in label else PALE)
    for index in range(4):
        arrow(draw, (rects[index][2], (rects[index][1] + rects[index][3]) // 2), (rects[index + 1][0], (rects[index + 1][1] + rects[index + 1][3]) // 2))
    poly_arrow(draw, [(rects[4][2] - 40, rects[4][3]), (rects[4][2] - 40, 760), (rects[5][0] + 40, 760), (rects[5][0] + 40, rects[5][1])])
    for index in range(5, 9):
        arrow(draw, (rects[index][2], (rects[index][1] + rects[index][3]) // 2), (rects[index + 1][0], (rects[index + 1][1] + rects[index + 1][3]) // 2))
    draw.text((90, 1320), "每一阶段输出均包含版本、来源、校验状态和不可变指纹；配置变化使旧预览、旧校验及旧评估失效。", fill=MID, font=SMALL)
    save(image, "figure-01-overall-flow.png")


def figure_2() -> None:
    image, draw = canvas("系统模块结构")
    layers = [
        ("交互与智能辅助层", ["用户项目入口", "Web工作台", "可选大语言模型适配器"]),
        ("控制与语义层", ["受控请求解析", "场景中间表示", "能力目录与策略门禁"]),
        ("确定性建模层", ["设施资源编译器", "结构/材料/网格编译", "TNT-ALE-FSI提供器", "关键字写入器"]),
        ("验证与证据层", ["静态校验", "LS-PrePost导入", "求解结果核验", "毁伤判据匹配", "不可变证据库"]),
    ]
    y = 210
    for layer_index, (name, modules) in enumerate(layers):
        draw.rounded_rectangle((90, y, 2310, y + 245), radius=16, fill=WHITE, outline=INK, width=4)
        draw.rectangle((90, y, 430, y + 245), fill=LIGHT, outline=INK, width=4)
        centered_text(draw, (105, y + 20, 415, y + 225), name, HEAD)
        available = 1820
        gap = 24
        module_width = (available - gap * (len(modules) - 1)) // len(modules)
        x = 470
        for module in modules:
            box(draw, (x, y + 52, x + module_width, y + 193), module, fnt=SMALL)
            x += module_width + gap
        if layer_index < len(layers) - 1:
            arrow(draw, (1200, y + 245), (1200, y + 315))
        y += 315
    save(image, "figure-02-system-architecture.png")


def figure_3() -> None:
    image, draw = canvas("受控解析、场景中间表示与能力匹配")
    inputs = ["设施模型或资源标识", "爆炸工况描述", "单位与参数来源", "目标输出与审核等级"]
    for i, text in enumerate(inputs):
        box(draw, (90, 240 + i * 225, 570, 390 + i * 225), text, fnt=SMALL)
        arrow(draw, (570, 315 + i * 225), (760, 625))
    box(draw, (760, 400, 1370, 850), "场景中间表示\n\n设施类型与结构体系\n几何、构件、材料和连接\n爆源、空气域、边界和耦合\n求解控制与输出请求\n字段来源、假设及待确认项", fill=LIGHT, fnt=SMALL)
    arrow(draw, (1370, 625), (1550, 625))
    box(draw, (1550, 300, 2290, 565), "能力声明匹配\n支持的设施、结构、载荷提供器、单位范围、资源预算和程序版本", fnt=SMALL)
    diamond(draw, (1920, 820), (600, 290), "关键字段齐全且能力可满足？")
    arrow(draw, (1920, 565), (1920, 675))
    box(draw, (1500, 1080, 1880, 1290), "追问、拒绝或转人工复核", fnt=SMALL)
    box(draw, (1980, 1080, 2290, 1290), "形成受控编译任务", fill=LIGHT, fnt=SMALL)
    arrow(draw, (1770, 900), (1690, 1080), label="否")
    arrow(draw, (2070, 900), (2140, 1080), label="是")
    save(image, "figure-03-semantic-capability.png")


def figure_4() -> None:
    image, draw = canvas("确定性物理模型编译与关键字文件生成")
    stages = [
        ("设施资源工件", "参数化几何\n构件拓扑\n接口与角色"),
        ("物理编译", "实体/壳/梁单元\n材料与截面\n钢筋与连接"),
        ("爆炸场景装配", "TNT体积\nALE空气域\n地面与边界\nFSI暴露面"),
        ("依赖闭包", "ID分配\n引用检查\n固定卡片顺序\n目标版本格式"),
        ("原子发布", "model.k\nmodel.json\nmanifest.json\nchecks.json"),
    ]
    x = 75
    widths = [390, 420, 430, 420, 420]
    for i, ((title, detail), w) in enumerate(zip(stages, widths)):
        rect = (x, 300, x + w, 1020)
        draw.rounded_rectangle(rect, radius=14, fill=PALE, outline=INK, width=4)
        draw.rectangle((x, 300, x + w, 410), fill=LIGHT, outline=INK, width=4)
        centered_text(draw, (x + 15, 310, x + w - 15, 400), title, HEAD)
        centered_text(draw, (x + 25, 450, x + w - 25, 960), detail, BODY)
        if i < len(stages) - 1:
            arrow(draw, (x + w, 660), (x + w + 52, 660))
        x += w + 52
    draw.text((90, 1180), "相同输入、资源版本和编译器版本产生相同规范化输出及相同包指纹；任何输入或资源变化均形成新修订。", fill=MID, font=SMALL)
    save(image, "figure-04-deterministic-compiler.png")


def figure_5() -> None:
    image, draw = canvas("爆炸场景的ALE空气域、TNT装药与结构FSI耦合关系")
    draw.rectangle((180, 280, 1750, 1160), fill=WHITE, outline=INK, width=5)
    draw.text((210, 300), "多材料ALE空气域 Ωa", fill=INK, font=HEAD)
    draw.rectangle((240, 1010, 1690, 1160), fill=LIGHT, outline=INK, width=4)
    centered_text(draw, (240, 1010, 1690, 1160), "支承地面与非反射边界", SMALL)
    draw.rectangle((790, 500, 1390, 1010), fill=PALE, outline=INK, width=5)
    draw.text((870, 720), "关键基础设施结构域 Ωs", fill=INK, font=HEAD)
    for x in (850, 1050, 1250):
        draw.line((x, 560, x, 970), fill=INK, width=8)
    for y in (610, 760, 910):
        draw.line((830, y, 1350, y), fill=INK, width=8)
    charge_center = (520, 720)
    draw.ellipse((450, 650, 590, 790), fill=LIGHT, outline=INK, width=5)
    centered_text(draw, (445, 645, 595, 795), "TNT\nΩe", HEAD)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        arrow(draw, charge_center, (int(520 + 230 * math.cos(rad)), int(720 + 230 * math.sin(rad))), width=3)
    for y in (560, 680, 800, 920):
        arrow(draw, (710, y), (790, y), label="FSI")
    right = [
        ("装药体积", "r=(3m/4πρ)^(1/3)"),
        ("流固耦合面", "S_FSI⊂∂Ωs"),
        ("单位系统", "m、s、kg、N、Pa"),
        ("边界条件", "空气域外边界、地面支承及接触关系"),
    ]
    for i, (name, detail) in enumerate(right):
        box(draw, (1840, 300 + i * 250, 2290, 490 + i * 250), f"{name}\n{detail}", fnt=SMALL)
        arrow(draw, (1750, 395 + i * 250), (1840, 395 + i * 250))
    save(image, "figure-05-ale-fsi-physics.png")


def figure_6() -> None:
    image, draw = canvas("多级校验、警告确认与生成就绪门禁")
    gates = [
        ("G1 结构化输入校验", "必填字段、类型、范围、单位和标识符"),
        ("G2 物理与依赖校验", "材料/状态方程、单元角色、引用闭包、FSI表面"),
        ("G3 规模与预算校验", "节点、单元、空气域、输出频率和资源预算"),
        ("G4 外部程序校验", "LS-PrePost导入、目标版本关键字和求解初始化"),
        ("G5 结果证据校验", "运行身份、时程覆盖、结果完整性和对象映射"),
    ]
    y = 210
    for i, (name, detail) in enumerate(gates):
        x1 = 160 + i * 95
        x2 = 2240 - i * 95
        box(draw, (x1, y, x2, y + 170), f"{name}\n{detail}", fill=LIGHT if i in (0, 4) else PALE, fnt=SMALL)
        if i < len(gates) - 1:
            arrow(draw, (1200, y + 170), (1200, y + 220))
        y += 220
    diamond(draw, (1200, 1350), (760, 190), "无阻断错误且当前警告已绑定修订确认？")
    box(draw, (90, 1260, 610, 1430), "否：定位问题、修正参数并重新校验", fnt=SMALL)
    box(draw, (1790, 1260, 2310, 1430), "是：开放K包生成或评估报告输出", fill=LIGHT, fnt=SMALL)
    arrow(draw, (820, 1350), (610, 1350), label="否")
    arrow(draw, (1580, 1350), (1790, 1350), label="是")
    save(image, "figure-06-readiness-gates.png")


def figure_7() -> None:
    image, draw = canvas("不可变项目修订与证据溯源关系")
    nodes = {
        "revision": (900, 240, 1500, 420, "项目修订 rN\n场景、资源及参数快照"),
        "model": (120, 560, 620, 760, "模型证据\nmodel.k与模型指纹"),
        "manifest": (720, 560, 1220, 760, "生成证据\nmanifest、依赖闭包与编译器版本"),
        "run": (1320, 560, 1820, 760, "运行证据\n求解器身份、运行ID和结果文件"),
        "threshold": (1920, 560, 2320, 760, "判据证据\n阈值档案、来源和适用范围"),
        "metrics": (420, 990, 1020, 1190, "对象级物理指标\n压力、冲量、应力、位移和损伤"),
        "report": (1380, 990, 1980, 1190, "毁伤评估报告\n等级、控制指标、异常及工程提示"),
    }
    for key, (x1, y1, x2, y2, text) in nodes.items():
        box(draw, (x1, y1, x2, y2), text, fill=LIGHT if key in ("revision", "report") else PALE, fnt=SMALL)
    for key in ("model", "manifest", "run", "threshold"):
        rect = nodes[key]
        arrow(draw, (1200, 420), ((rect[0] + rect[2]) // 2, rect[1]))
    arrow(draw, (370, 760), (650, 990))
    arrow(draw, (1070, 760), (900, 990))
    arrow(draw, (1570, 760), (1530, 990))
    arrow(draw, (2120, 760), (1800, 990))
    arrow(draw, (1020, 1090), (1380, 1090))
    draw.text((320, 1320), "证据身份 H=SHA-256(规范化项目修订∥模型∥运行∥指标∥阈值)；任一组成变化均产生新报告身份。", fill=MID, font=SMALL)
    save(image, "figure-07-evidence-provenance.png")


def figure_8() -> None:
    image, draw = canvas("可选大语言模型受控工具调用实施方式")
    box(draw, (90, 300, 470, 620), "用户提交\n设施项目、爆炸目标、参数资料和评估请求", fill=LIGHT, fnt=SMALL)
    box(draw, (630, 240, 1120, 680), "大语言模型适配器\n识别意图\n提取候选字段\n提出缺失问题\n生成工具调用建议", fnt=SMALL)
    box(draw, (1300, 240, 1810, 680), "确定性控制器\nSchema校验\n能力匹配\n权限与审批\n状态机及重试预算", fill=LIGHT, fnt=SMALL)
    box(draw, (1980, 300, 2310, 620), "受控工具网关\n建模、预览、校验、生成和结果读取", fnt=SMALL)
    arrow(draw, (470, 460), (630, 460))
    arrow(draw, (1120, 460), (1300, 460), label="候选动作")
    arrow(draw, (1810, 460), (1980, 460), label="批准动作")
    box(draw, (720, 900, 1680, 1180), "确定性工程内核及不可变项目\n大语言模型不能直接访问文件系统，不能直接写入K文件，不能修改判据或提升工程验证状态。", fill=LIGHT, fnt=SMALL)
    arrow(draw, (2145, 620), (1680, 990))
    arrow(draw, (1200, 900), (1200, 680), label="工具结果与校验发现")
    poly_arrow(draw, [(720, 1040), (300, 1040), (300, 620)], label="追问或人工确认")
    draw.line((530, 760, 1870, 760), fill=INK, width=4)
    draw.text((760, 720), "控制边界：模型建议权与工程执行权分离", fill=INK, font=HEAD)
    save(image, "figure-08-llm-controlled-tools.png")


def main() -> None:
    for generator in (figure_1, figure_2, figure_3, figure_4, figure_5, figure_6, figure_7, figure_8):
        generator()
    print(f"generated=8 output={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
