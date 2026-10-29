from __future__ import annotations

import json
import shutil
import unicodedata
import zipfile
from xml.etree import ElementTree
from pathlib import Path

try:
    from .work_paths import PROJECT_ROOT, existing_input, generated_path
except ImportError:  # Direct script invocation.
    from work_paths import PROJECT_ROOT, existing_input, generated_path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = PROJECT_ROOT
WORK = generated_path("soft_copyright_work")
TEMPLATES = existing_input("soft_copyright_work", "templates_docx")
OUTPUT = WORK / "outputs"
SCREENSHOT_DIR = existing_input("soft_copyright_work", "runtime_screens_v2")
SOURCE_MANUAL = Path("E:/Desktop/城市关键基础设施爆炸毁伤数字化建模与智能评估系统V1.0-软件设计与操作说明书.docx")

SOFTWARE_NAME = "城市关键基础设施爆炸毁伤数字化建模与智能评估系统"
SHORT_NAME = "城市关键基础设施爆炸毁伤智能评估系统"
VERSION = "V1.0"

MAIN_FUNCTIONS = (
    "本软件面向住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等城市关键基础设施的爆炸冲击数字化建模、求解验证与毁伤评估业务，提供项目创建、设施类型选择、结构体系配置、构件参数录入、材料与网格设置、爆源及流体域设置、模型预览、静态校验、关键字生成、外部求解、结果读取、毁伤分级和报告归档等功能。"
    "软件采用统一设施语义模型管理空间尺寸、洞口、承重构件、非承重构件、钢筋或钢构连接、支承地面、材料本构、网格策略、边界条件和爆炸载荷等数据，并根据构件物理角色确定性选择Solid、Shell或Beam单元族，检查节点与部件引用、连接连续性、承重路径、接触关系、流体暴露面和单位制一致性，减少手工编写关键字时容易出现的漏项、错引和物理关系冲突。"
    "在爆炸工况配置方面，软件支持TNT当量、爆源坐标、起爆时间、多材料ALE空气域、独立地面、非反射边界、状态方程及ALE-Lagrange流固耦合参数的受控设置，并在分层三维预览中显示主体结构、空腔与洞口、钢筋与连接、非承重构件、爆源、流体域、边界和支承地面，用户可切换图层和观察方向核对模型空间关系。"
    "软件能够将当前项目编译为LS-DYNA模型文件和配套清单，对生成内容执行结构化重解析、卡片引用检查、能力声明匹配、预算限制检查和分级就绪门禁；在外部程序可用时，可继续执行LS-PrePost导入检查、LS-DYNA模型检查及短时求解验证，并记录模型指纹、运行标识、日志、结果文件和验证摘要。"
    "在智能毁伤评估方面，软件仅对通过结果身份、时间覆盖、数据完整性和对象映射门禁的求解结果进行分析，自动提取压力峰值、正相冲量、结构应力、位移、材料损伤、单元删除和流固耦合时间等具有物理依据的指标，将指标与已复核或经用户确认的受控毁伤判据进行匹配，形成对象级低、关注、较高、严重或无法评估等级，并按关键基础设施、区域和构件层级汇总最不利等级、关键部位及主要控制指标。"
    "系统还能够识别结果缺失、单位不一致、阈值来源不适用、观察时长不足和指标相互矛盾等异常，避免将不完整结果自动表述为确定性毁伤结论；最终输出JSON数据和HTML评估报告，并建立模型、载荷、求解结果、阈值来源、等级结论和报告文件之间的证据索引，实现项目版本、关键字文件、运行过程和评估结论的一致性校验与可追溯管理。"
)

INFO_OUTPUT = OUTPUT / f"附件3：{SOFTWARE_NAME}{VERSION}-软著信息采集表.docx"
MANUAL_OUTPUT = OUTPUT / f"附件4：{SOFTWARE_NAME}{VERSION}-软件设计与操作说明书.docx"
CODE_OUTPUT = OUTPUT / f"附件5：{SOFTWARE_NAME}{VERSION}-源程序代码.docx"
MANIFEST_OUTPUT = WORK / "code_selection_manifest.json"


def set_run_font(run, name: str, size: float, *, bold: bool | None = None, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def set_cell_text(cell, text: str, *, placeholder: bool = False, size: float = 10.5):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.15
    run = paragraph.add_run(text)
    set_run_font(run, "宋体", size, color=(192, 0, 0) if placeholder else None)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if placeholder:
        tc_pr = cell._tc.get_or_add_tcPr()
        shading = tc_pr.find(qn("w:shd"))
        if shading is None:
            shading = OxmlElement("w:shd")
            tc_pr.append(shading)
        shading.set(qn("w:fill"), "FFF2CC")


def strip_word_comments(path: Path):
    temporary = path.with_suffix(".comments-cleaned.docx")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            lower_name = item.filename.lower()
            if lower_name.startswith("word/comments"):
                continue
            data = source.read(item.filename)
            if item.filename == "[Content_Types].xml" or item.filename.endswith(".rels"):
                root = ElementTree.fromstring(data)
                for element in list(root):
                    attributes = " ".join(element.attrib.values()).lower()
                    if "comment" in attributes:
                        root.remove(element)
                data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            elif item.filename == "word/document.xml":
                root = ElementTree.fromstring(data)
                for parent in root.iter():
                    for child in list(parent):
                        if child.tag.rsplit("}", 1)[-1] in {"commentRangeStart", "commentRangeEnd", "commentReference"}:
                            parent.remove(child)
                data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, data)
    temporary.replace(path)


def fill_information_form():
    source = TEMPLATES / "附件3：软著新系统信息采集表模板.docx"
    document = Document(source)
    table = document.tables[0]

    values = {
        2: SOFTWARE_NAME,
        3: SHORT_NAME,
        4: VERSION,
        5: "应用软件",
        6: "[待填写：YYYY年MM月DD日]",
        7: "[待确认：未发表/已发表；如已发表请补充日期和地点]",
        8: "[待填写：公司或个人名称]",
        9: "[待填写：统一社会信用代码或身份证号码]",
        10: "[待填写：营业执照或身份证所属城市]",
        11: "x64计算机，建议八核处理器、16 GB以上内存，并为模型、结果文件和验证证据预留充足存储空间。",
        12: "x64四核及以上计算机，8 GB以上内存，10 GB以上可用磁盘空间；大型ALE模型按规模增加内存和存储。",
        13: "Windows 10/11 64位操作系统。",
        14: "Python 3.10及以上、Git、pytest、Node.js及浏览器开发工具；LS-PrePost和LS-DYNA用于外部验证。",
        15: "Windows 10/11 64位操作系统，支持WebGL的Microsoft Edge或Google Chrome浏览器。",
        16: "Python 3.10及以上；可选LS-PrePost或LS-DYNA本地安装，用于模型导入、检查和求解验证。",
        17: "Python 3.10及以上、JavaScript、HTML5、CSS3。",
        18: "约46,923行（核心模块；正式交存前按冻结版本复核）。",
        19: "面向城市关键基础设施爆炸冲击分析，形成从设施语义配置、物理构件编译、求解型K文件生成到结果证据核验、毁伤分级和报告输出的一体化本地工作流，降低重复建模、关键字引用缺失、物理关系不一致和评估依据不可追溯等风险。",
        20: "智慧城市、城市关键基础设施安全、爆炸冲击有限元分析、工程仿真与毁伤评估。",
        21: MAIN_FUNCTIONS,
        22: "15.智慧城市软件",
        23: "采用设施语义工件、确定性物理编译、闭合ALE/FSI配置、多级验证门禁、受控毁伤阈值和不可变证据绑定，实现模型、求解结果、毁伤等级及判据来源一致可追溯。",
        25: "[待填写]",
        26: "[待填写]",
        27: "[待填写]",
        28: "[待填写]",
    }
    placeholders = {6, 7, 8, 9, 10, 25, 26, 27, 28}
    for row_index, value in values.items():
        set_cell_text(table.rows[row_index].cells[1], value, placeholder=row_index in placeholders)

    document.core_properties.title = f"{SOFTWARE_NAME}{VERSION}软著信息采集表"
    document.core_properties.subject = "计算机软件著作权登记信息采集"
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.save(INFO_OUTPUT)
    strip_word_comments(INFO_OUTPUT)


def replace_paragraph_text(paragraph, old: str, new: str):
    if old not in paragraph.text:
        return False
    text = paragraph.text.replace(old, new)
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)
    return True


def delete_paragraph(paragraph):
    element = paragraph._element
    element.getparent().remove(element)
    paragraph._p = paragraph._element = None


def insert_paragraph_before(anchor, text: str, *, style: str | None = None, page_break: bool = False, bold: bool = False):
    paragraph = anchor.insert_paragraph_before()
    if style:
        paragraph.style = style
    paragraph.paragraph_format.page_break_before = page_break
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.line_spacing = 1.35
    if style == "Normal":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.first_line_indent = Cm(0.74)
    run = paragraph.add_run(text)
    set_run_font(run, "宋体", 10.5, bold=bold)
    return paragraph


def insert_operation_step(anchor, text: str):
    paragraph = insert_paragraph_before(anchor, text, style="List Number")
    paragraph.paragraph_format.first_line_indent = Cm(0)
    return paragraph


def insert_picture_before(anchor, image_name: str, caption: str):
    image_path = SCREENSHOT_DIR / image_name
    if not image_path.exists():
        raise FileNotFoundError(image_path)
    paragraph = anchor.insert_paragraph_before()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.add_run().add_picture(str(image_path), width=Cm(16.4))
    caption_paragraph = anchor.insert_paragraph_before()
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_paragraph.paragraph_format.space_before = Pt(0)
    caption_paragraph.paragraph_format.space_after = Pt(8)
    caption_run = caption_paragraph.add_run(caption)
    set_run_font(caption_run, "宋体", 9.5)


def update_manual_toc_titles(document: Document):
    replacements = {
        "11.1 启动软件": "11.1 软件启动与项目入口",
        "11.2 工作台总体界面": "11.2 精细化建模工作台总体界面",
        "11.3 选择关键基础设施": "11.3 关键基础设施与结构体系配置",
        "11.4 配置真实ALE/FSI载荷": "11.4 材料参数与网格策略配置",
        "11.5 保存、验证、生成与评估": "11.5 爆炸载荷与真实ALE/FSI配置",
        "11.6 预览图层": "11.6 分层三维预览与图层控制",
        "11.7 外部程序操作": "11.7 保存、校验与K包生成",
    }
    for paragraph in document.paragraphs:
        if paragraph.style.name != "toc 2":
            continue
        title, separator, page_number = paragraph.text.partition("\t")
        if title in replacements:
            paragraph.text = replacements[title] + (separator + page_number if separator else "")
            for run in paragraph.runs:
                set_run_font(run, "宋体", 10.5)
    toc_chapter_12 = next(
        paragraph for paragraph in document.paragraphs
        if paragraph.style.name == "toc 1" and paragraph.text.startswith("12 ")
    )
    toc_118 = toc_chapter_12.insert_paragraph_before("11.8 智能毁伤评估与报告输出\t待更新")
    toc_118.style = "toc 2"


def rebuild_operation_chapter(document: Document):
    chapter_11 = next(
        paragraph for paragraph in document.paragraphs
        if paragraph.style.name == "Heading 1" and paragraph.text.strip() == "11 软件操作说明"
    )
    chapter_12 = next(
        paragraph for paragraph in document.paragraphs
        if paragraph.style.name == "Heading 1" and paragraph.text.strip().startswith("12 项目版本")
    )
    paragraphs = document.paragraphs
    start = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is chapter_11._p)
    end = next(index for index, paragraph in enumerate(paragraphs) if paragraph._p is chapter_12._p)
    for paragraph in paragraphs[start + 1:end]:
        delete_paragraph(paragraph)
    chapter_12.paragraph_format.page_break_before = True

    anchor = chapter_12
    insert_paragraph_before(anchor, "11.1 软件启动与项目入口", style="Heading 2")
    insert_paragraph_before(
        anchor,
        "用户在Windows环境中运行start_web_app.cmd或scripts/start_web_app.ps1启动本地服务，浏览器打开软件首页后可查看项目列表、场景配置、建模预览、检查结果和影响评估入口。界面顶部显示登记软件全称，确保采集表、说明书和运行画面中的软件身份一致。",
        style="Normal",
    )
    insert_operation_step(anchor, "确认Python环境及项目目录可访问，启动本地Web服务。")
    insert_operation_step(anchor, "在浏览器中打开系统首页，检查服务状态和项目目录状态。")
    insert_operation_step(anchor, "单击“关键基础设施精细化爆炸”进入独立建模工作台。")
    insert_picture_before(anchor, "01-launch-workbench.png", "图11-1 软件启动后的项目工作台界面")

    insert_paragraph_before(anchor, "11.2 精细化建模工作台总体界面", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "精细化建模工作台由左侧八步配置导航、中部三维预览区、右侧配置与检查面板以及底部保存、预览、校验、生成和外部程序操作区组成。顶部状态区持续显示项目标识、草稿保存状态和检查状态，使当前版本及后续动作条件保持可见。",
        style="Normal",
    )
    insert_picture_before(anchor, "02-refined-overview.png", "图11-2 精细化建模工作台总体运行界面")
    insert_paragraph_before(
        anchor,
        "八步导航依次覆盖空间与洞口、结构体系、连接、构件、材料、网格、爆源和最终检查。用户切换步骤时，右侧仅显示与当前关键基础设施类型和结构体系相适用的字段，减少无关参数对操作过程的干扰。",
        style="Normal",
    )

    insert_paragraph_before(anchor, "11.3 关键基础设施与结构体系配置", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "进入结构配置步骤后，用户选择住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊或加油站等关键基础设施模块，并配置适用的结构体系、主要空间尺寸、楼层或跨径、洞口及承重构件参数。系统依据能力声明限制可选项，并同步更新构件关系和预览。",
        style="Normal",
    )
    insert_operation_step(anchor, "在设施类型列表中选择本项目对应的关键基础设施模块。")
    insert_operation_step(anchor, "选择结构体系，录入尺寸、洞口、承重构件和连接参数。")
    insert_operation_step(anchor, "查看右侧字段适用性提示和中部模型空间关系。")
    insert_picture_before(anchor, "03-structure-configuration.png", "图11-3 关键基础设施结构体系与承重构件配置界面")

    insert_paragraph_before(anchor, "11.4 材料参数与网格策略配置", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "材料配置界面用于选择混凝土、钢材、空气和炸药等材料模型及相应参数，并保持材料、状态方程和单位制之间的一致关系。系统根据构件物理角色关联适用材料，不允许把不匹配的材料参数直接发布到当前模型。",
        style="Normal",
    )
    insert_picture_before(anchor, "04-material-configuration.png", "图11-4 材料模型与状态方程配置界面")
    insert_paragraph_before(anchor, "网格策略配置", style="Normal", page_break=True, bold=True)
    insert_paragraph_before(
        anchor,
        "网格步骤用于设置结构单元尺寸、流体域单元尺寸、局部加密区域和模型规模预算。界面同时给出节点、单元、部件及耦合关系的估算信息；当预计规模超过能力声明或预算限制时，系统在生成前给出阻断或警告。",
        style="Normal",
    )
    insert_picture_before(anchor, "05-mesh-configuration.png", "图11-5 网格策略与模型规模预算配置界面")

    insert_paragraph_before(anchor, "11.5 爆炸载荷与真实ALE/FSI配置", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "爆源步骤用于设置TNT当量、爆源坐标、起爆时间、空气域、地面、边界及流固耦合参数。用户调整爆源位置或载荷参数后，旧预览和旧校验状态自动失效，必须保存当前修订并重新预览、重新校验，防止沿用与当前工况不一致的结果。",
        style="Normal",
    )
    insert_operation_step(anchor, "选择受控载荷提供器并设置TNT当量、爆源坐标和起爆时间。")
    insert_operation_step(anchor, "配置ALE空气域、网格尺寸、边界距离、地面及终止时间。")
    insert_operation_step(anchor, "核对FSI暴露面、耦合关系和单位制提示。")
    insert_picture_before(anchor, "06-blast-load-configuration.png", "图11-6 爆炸载荷与ALE/FSI参数配置界面")

    insert_paragraph_before(anchor, "11.6 分层三维预览与图层控制", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "用户保存有效草稿后单击“刷新预览”，系统根据当前持久化修订生成三维模型。预览支持等轴、正视、俯视和适配视角，并可独立显示或隐藏空腔与洞口、主体结构、钢筋与连接、非承重构件、暴露面、爆源、流体域、边界和支承地面。该预览用于核对空间关系和配置完整性，不替代LS-PrePost导入或求解验证。",
        style="Normal",
    )
    insert_picture_before(anchor, "07-layered-preview.png", "图11-7 三维模型预览与九类图层控制界面")

    insert_paragraph_before(anchor, "11.7 保存、校验与K包生成", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "最终检查步骤汇总即时检查、规模预算、警告确认、当前修订和生成条件。用户先保存草稿，再验证当前版本；错误必须修正，警告需确认并绑定当前修订。只有分级就绪门禁通过后，“生成K包”才可用，生成结果包含model.k、模型清单、配置快照、指纹和证据索引。",
        style="Normal",
    )
    insert_operation_step(anchor, "保存当前草稿并取得项目修订号。")
    insert_operation_step(anchor, "单击“验证”，处理错误、预算超限和需要确认的警告。")
    insert_operation_step(anchor, "门禁通过后生成K包；需要时使用受控凭证打开LS-PrePost或启动LS-DYNA。")
    insert_picture_before(anchor, "08-validation-and-generation.png", "图11-8 即时检查、预算门禁与K包生成界面")

    insert_paragraph_before(anchor, "11.8 智能毁伤评估与报告输出", style="Heading 2", page_break=True)
    insert_paragraph_before(
        anchor,
        "求解结束并登记结果后，用户进入“影响评估”界面读取评估。系统先校验模型指纹、运行标识、结果文件完整性、时间覆盖和对象映射，再提取压力、冲量、应力、位移、材料损伤等物理指标，与受控判据档案匹配，输出低、关注、较高、严重或无法评估等级。",
        style="Normal",
    )
    insert_operation_step(anchor, "选择已完成外部验证且已登记结果证据的项目。")
    insert_operation_step(anchor, "单击“读取评估”，查看设施、区域和构件对象的毁伤等级及控制指标。")
    insert_operation_step(anchor, "核对阈值来源、异常提示和证据摘要，导出JSON数据及HTML评估报告。")
    insert_picture_before(anchor, "09-intelligent-damage-assessment.png", "图11-9 城市关键基础设施智能毁伤评估界面")
    insert_paragraph_before(
        anchor,
        "当结果证据不完整、观察时长不足、指标单位不一致或判据不适用于当前对象时，界面显示“无法评估”并列出原因，不自动生成确定性毁伤结论。所有等级均保留模型、运行、指标和阈值来源的关联信息，供工程人员复核。",
        style="Normal",
    )


def prepare_manual():
    shutil.copy2(SOURCE_MANUAL, MANUAL_OUTPUT)
    document = Document(MANUAL_OUTPUT)
    replacements = {
        "优化适配稿 · 供专业机构复核与完善": "软件著作权登记材料",
        "用于软件著作权登记的软件文档鉴别材料初稿": "用于软件著作权登记的软件设计与操作说明书",
        "附录B 软件著作权申请信息初稿": "附录B 软件著作权申请信息",
    }
    for paragraph in document.paragraphs:
        for old, new in replacements.items():
            replace_paragraph_text(paragraph, old, new)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    replace_paragraph_text(paragraph, "初稿内容", "填写内容")

    update_manual_toc_titles(document)
    rebuild_operation_chapter(document)

    document.core_properties.title = f"{SOFTWARE_NAME}{VERSION}软件设计与操作说明书"
    document.core_properties.subject = "计算机软件著作权登记软件说明书"
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.save(MANUAL_OUTPUT)


def code_files() -> list[Path]:
    selected: list[Path] = []
    for path in sorted((ROOT / "lsprepost_mcp").rglob("*")):
        if path.is_file() and path.suffix.lower() in {".py", ".js", ".css", ".html"} and "vendor" not in path.parts:
            selected.append(path)
    for path in sorted((ROOT / "web" / "src").rglob("*")):
        if path.is_file() and path.suffix.lower() in {".js", ".jsx", ".css", ".html"}:
            selected.append(path)
    return selected


def width_units(text: str) -> int:
    total = 0
    for char in text:
        total += 2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1
    return total


def split_visual_line(text: str, limit: int = 112) -> list[str]:
    text = text.expandtabs(4).rstrip()
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    first = True
    while width_units(remaining) > limit:
        used = 0
        cut = 0
        for index, char in enumerate(remaining):
            used += 2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1
            if used > limit:
                break
            cut = index + 1
        if cut <= 0:
            cut = 1
        preferred = max(remaining.rfind(" ", 0, cut), remaining.rfind(",", 0, cut), remaining.rfind(")", 0, cut))
        if preferred >= max(20, cut - 25):
            cut = preferred + 1
        piece = remaining[:cut].rstrip()
        chunks.append(piece if first else "    " + piece.lstrip())
        remaining = remaining[cut:].lstrip()
        first = False
    chunks.append(remaining if first else "    " + remaining)
    return chunks


def source_stream() -> tuple[list[str], list[dict]]:
    stream: list[str] = []
    files_meta: list[dict] = []
    for path in code_files():
        relative = path.relative_to(ROOT).as_posix()
        suffix = path.suffix.lower()
        if suffix == ".py":
            marker = f"# source: {relative}"
        elif suffix == ".html":
            marker = f"<!-- source: {relative} -->"
        else:
            marker = f"// source: {relative}"
        start = len(stream)
        stream.append(marker)
        raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        source_nonblank = 0
        for raw in raw_lines:
            if not raw.strip():
                continue
            source_nonblank += 1
            stream.extend(split_visual_line(raw))
        files_meta.append(
            {
                "path": relative,
                "source_nonblank_lines": source_nonblank,
                "display_start": start,
                "display_end": len(stream),
            }
        )
    return stream, files_meta


def set_cell_margins(cell, top=0, start=50, bottom=0, end=50):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin_name, margin_value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin_name}"))
        if node is None:
            node = OxmlElement(f"w:{margin_name}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(margin_value))
        node.set(qn("w:type"), "dxa")


def remove_table_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "nil")


def add_code_page(document: Document, lines: list[str], page_number: int):
    for index, line in enumerate(lines):
        paragraph = document.add_paragraph()
        if index == 0 and page_number > 1:
            paragraph.paragraph_format.page_break_before = True
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = Pt(10.2)
        paragraph.paragraph_format.keep_together = True
        paragraph.paragraph_format.keep_with_next = False
        paragraph.paragraph_format.widow_control = False
        run = paragraph.add_run(line)
        set_run_font(run, "Consolas", 7.2)


def build_code_document():
    stream, files_meta = source_stream()
    if len(stream) < 4000:
        raise RuntimeError(f"Source stream has only {len(stream)} printable lines")
    selected = stream[:2000] + stream[-2000:]
    if len(selected) != 4000:
        raise RuntimeError("Code selection did not produce 4000 lines")

    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(1.5)
    section.right_margin = Cm(1.5)

    for page_index in range(80):
        add_code_page(document, selected[page_index * 50 : (page_index + 1) * 50], page_index + 1)

    document.core_properties.title = f"{SOFTWARE_NAME}{VERSION}源程序代码"
    document.core_properties.subject = "计算机软件著作权登记源程序鉴别材料"
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.save(CODE_OUTPUT)

    manifest = {
        "software": SOFTWARE_NAME,
        "version": VERSION,
        "source_file_count": len(files_meta),
        "printable_stream_lines": len(stream),
        "submitted_lines": len(selected),
        "pages": 80,
        "lines_per_page": 50,
        "layout": "plain_code_without_tables_line_numbers_headers_or_page_numbers",
        "first_segment": {"start": 0, "end": 2000},
        "last_segment": {"start": len(stream) - 2000, "end": len(stream)},
        "last_printed_line": selected[-1],
        "files": files_meta,
    }
    MANIFEST_OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fill_information_form()
    prepare_manual()
    build_code_document()
    print(INFO_OUTPUT)
    print(MANUAL_OUTPUT)
    print(CODE_OUTPUT)


if __name__ == "__main__":
    main()
