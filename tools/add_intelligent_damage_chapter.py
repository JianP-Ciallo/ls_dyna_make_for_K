from __future__ import annotations

from pathlib import Path
import re
import sys

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def clear_and_set(paragraph, text: str) -> None:
    p_pr = paragraph._p.pPr
    for child in list(paragraph._p):
        if child is not p_pr:
            paragraph._p.remove(child)
    paragraph.add_run(text)


def set_cell_text(cell, text: str) -> None:
    clear_and_set(cell.paragraphs[0], text)
    for paragraph in cell.paragraphs[1:]:
        clear_and_set(paragraph, "")


def find_exact(doc: Document, text: str):
    matches = [p for p in doc.paragraphs if p.text.strip() == text]
    if len(matches) != 1:
        raise ValueError(f"expected one paragraph {text!r}, found {len(matches)}")
    return matches[0]


def add_before(anchor, text: str, style: str, *, page_break: bool = False):
    paragraph = anchor.insert_paragraph_before(text, style=style)
    if page_break:
        paragraph.paragraph_format.page_break_before = True
    return paragraph


def renumber_existing_chapters(doc: Document) -> None:
    heading_map = {
        "10 软件操作说明": "11 软件操作说明",
        "10.1 启动软件": "11.1 启动软件",
        "10.2 工作台总体界面": "11.2 工作台总体界面",
        "10.3 选择关键基础设施": "11.3 选择关键基础设施",
        "10.4 配置真实ALE/FSI载荷": "11.4 配置真实ALE/FSI载荷",
        "10.5 保存、验证、生成与评估": "11.5 保存、验证、生成与评估",
        "10.6 预览图层": "11.6 预览图层",
        "10.7 外部程序操作": "11.7 外部程序操作",
        "11 项目版本、证据与安全控制": "12 项目版本、证据与安全控制",
        "11.1 指纹体系": "12.1 指纹体系",
        "11.2 不可变修订": "12.2 不可变修订",
        "11.3 外部动作安全": "12.3 外部动作安全",
        "12 异常处理": "13 异常处理",
        "13 测试与验收证据": "14 测试与验收证据",
        "13.1 软件测试": "14.1 软件测试",
        "13.2 外部程序验收": "14.2 外部程序验收",
        "14 软件技术特点": "15 软件技术特点",
        "15 使用限制和工程复核": "16 使用限制和工程复核",
    }
    for paragraph in doc.paragraphs:
        current = paragraph.text.strip()
        if current in heading_map and paragraph.style.name.startswith("Heading"):
            clear_and_set(paragraph, heading_map[current])

    caption_replacements = {
        "图10-1": "图11-1",
        "图10-2": "图11-2",
        "图10-3": "图11-3",
        "图10-4": "图11-4",
        "图10-5": "图11-5",
        "图11-1": "图12-1",
    }
    # Avoid cascading 图10-1 -> 图11-1 -> 图12-1.
    for paragraph in doc.paragraphs:
        text = paragraph.text
        if text.startswith("图10-"):
            text = re.sub(r"^图10-", "图11-", text)
        elif text.startswith("图11-1"):
            text = text.replace("图11-1", "图12-1", 1)
        if text != paragraph.text:
            clear_and_set(paragraph, text)


def add_chapter(doc: Document) -> None:
    anchor = find_exact(doc, "11 软件操作说明")
    blocks = [
        ("10 城市关键基础设施智能毁伤评估", "Heading 1", True),
        (
            "本章说明系统在爆炸冲击有限元求解完成后，如何以城市关键基础设施及其构件为评估对象，自动完成结果证据核验、物理响应指标提取、毁伤判据匹配、等级确定、异常识别和报告生成。该流程由确定性程序执行，所有等级均可追溯至模型、结果文件、指标值和判据来源。",
            "Normal",
            False,
        ),
        ("10.1 评估对象语义识别", "Heading 2", False),
        (
            "系统读取model.json中的设施语义对象、部件编号、材料类别、结构角色、空间包围盒和响应输出请求，将住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等设施映射为可独立评估的对象集合。每个对象与有限元部件、FSI耦合面、壳单元、实体单元及历史节点建立明确对应关系，防止使用全局结果代替单个设施或构件响应。",
            "Normal",
            False,
        ),
        ("10.2 求解结果证据与就绪门禁", "Heading 2", False),
        (
            "智能评估前，系统核验model.k与model.json哈希、求解运行身份、d3plot序列连续性以及d3hsp、dbfsi、glstat、elout、nodout等必需结果文件。系统同时检查正常终止、时间覆盖率、非有限数值、负体积、能量异常和对象响应完整性。求解质量、对象级结果或判据来源任一条件不满足时，评估状态保持未就绪，不输出确定性毁伤等级。",
            "Normal",
            False,
        ),
        ("10.3 物理响应指标自动提取", "Heading 2", False),
        (
            "结果解析模块按语义对象自动提取峰值压力、正压力冲量、结构压力峰值、主应力峰值、最大位移、材料损伤指标、FSI到达时间、结构响应到达时间、到达后观察时长和结构响应信噪比。对于地面和基础区域，还可提取压力应力响应、向下位移、材料损伤及单元删除等爆坑形成证据。指标保留数值、单位、来源文件、对象标识和结果证据摘要。",
            "Normal",
            False,
        ),
        ("10.4 毁伤判据与阈值档案匹配", "Heading 2", False),
        (
            "毁伤判据采用受控阈值档案管理。阈值档案记录判据来源、复核状态、适用设施类别、适用材料、指标上下限及绑定的模型和材料契约哈希。只有状态为已复核或用户确认、来源完整且适用范围与当前模型一致的阈值档案才能参与分级；演示阈值、缺少来源的经验值或与当前模型不匹配的判据均被门禁拒绝。",
            "Normal",
            False,
        ),
        ("10.5 对象级毁伤等级判定", "Heading 2", False),
        (
            "系统将每项可用物理指标与对应的关注、较高和严重阈值比较，分别得到指标级等级，并以最不利适用指标形成对象级毁伤风险。等级分为低、关注、较高和严重四级；当结果证据、对象指标或适用判据不足时，输出无法评估。评估结果同时记录触发等级的指标、实际值、阈值等级、判据来源及工程提示。",
            "Normal",
            False,
        ),
        ("10.6 设施级汇总与异常识别", "Heading 2", False),
        (
            "系统按照设施、区域、构件和部件层级汇总对象级结果，形成关键部位清单、最高毁伤风险、受影响对象数量及部件风险映射。异常识别模块用于发现归一化位移异常、响应缺失、到达前噪声过大、时程覆盖不足和指标之间相互矛盾等情况；异常不会被自动解释为真实毁伤，而是作为阻断项或复核提示写入评估证据。",
            "Normal",
            False,
        ),
        ("10.7 智能评估报告与证据溯源", "Heading 2", False),
        (
            "系统输出city_impact_assessment.json和city_impact_report.html。报告包括项目名称、模型哈希、设施布局指纹、编辑状态指纹、求解结果身份、质量门禁、对象级物理指标、毁伤等级、触发依据、阈值来源、异常项和工程提示。模型、结果或判据发生变化时必须重新评估并形成新的报告身份，历史结论不得覆盖。",
            "Normal",
            False,
        ),
        ("10.8 大语言模型辅助解释边界", "Heading 2", False),
        (
            "系统预留大语言模型辅助接口，用于将已经通过门禁的物理指标、毁伤等级、判据来源和异常信息组织为自然语言说明，辅助用户理解评估结果。大语言模型不直接读取并改写K文件，不生成未经求解支持的物理指标，不修改阈值档案，也不越过确定性程序改变毁伤等级；其输出属于解释性内容，最终工程结论仍需专业人员复核。",
            "Normal",
            False,
        ),
    ]
    for text, style, page_break in blocks:
        add_before(anchor, text, style, page_break=page_break)


def remove_old_toc(doc: Document) -> None:
    for paragraph in list(doc.paragraphs):
        if paragraph.style.name.lower().startswith("toc"):
            paragraph._element.getparent().remove(paragraph._element)


def enable_field_updates(doc: Document) -> None:
    settings = doc.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")


def main() -> None:
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    doc = Document(source)
    renumber_existing_chapters(doc)
    add_chapter(doc)
    remove_old_toc(doc)
    enable_field_updates(doc)
    doc.save(destination)


if __name__ == "__main__":
    main()
