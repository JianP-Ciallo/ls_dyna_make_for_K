from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


SOFTWARE_NAME = "城市关键基础设施爆炸毁伤数字化建模与智能评估系统"
SOFTWARE_SHORT_NAME = "城市关键基础设施爆炸毁伤智能评估系统"


def replace_text_in_paragraph(paragraph: Paragraph, old: str, new: str) -> None:
    if old not in paragraph.text:
        return
    for run in paragraph.runs:
        if old in run.text:
            run.text = run.text.replace(old, new)
    if old not in paragraph.text:
        return
    full_text = paragraph.text.replace(old, new)
    if paragraph.runs:
        paragraph.runs[0].text = full_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(full_text)


def set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def find_paragraph(doc: Document, starts_with: str) -> Paragraph:
    matches = [p for p in doc.paragraphs if p.text.strip().startswith(starts_with)]
    if len(matches) != 1:
        raise ValueError(f"expected one paragraph starting with {starts_with!r}, found {len(matches)}")
    return matches[0]


def insert_paragraph_after(paragraph: Paragraph, text: str, style: str) -> Paragraph:
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    inserted = Paragraph(new_p, paragraph._parent)
    inserted.style = style
    inserted.add_run(text)
    return inserted


def set_cell_text(cell, text: str) -> None:
    paragraph = cell.paragraphs[0]
    set_paragraph_text(paragraph, text)
    for extra in cell.paragraphs[1:]:
        set_paragraph_text(extra, "")


def append_styled_row(table, values: list[str]) -> None:
    template = table.rows[-1]._tr
    new_tr = deepcopy(template)
    table._tbl.append(new_tr)
    row = table.rows[-1]
    for cell, value in zip(row.cells, values, strict=True):
        set_cell_text(cell, value)


def enable_field_updates(doc: Document) -> None:
    settings = doc.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")


def rewrite(source: Path, destination: Path) -> None:
    doc = Document(source)

    replacements = {
        "精细建筑结构爆炸冲击有限元建模与验证系统": SOFTWARE_NAME,
        "精细建筑爆炸冲击建模验证系统（暂定）": SOFTWARE_SHORT_NAME,
        "精细建筑爆炸冲击建模验证系统": SOFTWARE_SHORT_NAME,
        "精细化建筑爆炸工作台": "城市关键基础设施爆炸毁伤工作台",
    }
    for paragraph in doc.paragraphs:
        for old, new in replacements.items():
            replace_text_in_paragraph(paragraph, old, new)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for old, new in replacements.items():
                        replace_text_in_paragraph(paragraph, old, new)

    targeted = {
        "材料边界：": (
            "能力边界：本说明书描述V1.0已经形成的软件框架及可验证模块。系统已实现城市关键基础设施场景建模、"
            "爆炸冲击K文件生成、多级校验、求解结果来源核验、对象级响应指标提取、阈值档案匹配、毁伤风险分级和"
            "评估报告输出。住宅、商场和地铁入口已有LS-PrePost导入、LS-DYNA R12模型检查及短时传播验证证据；"
            "工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等纳入统一设施模块体系，具体工程应用时仍需"
            "补充相应材料、构造和毁伤判据。大语言模型可作为后续评估解释接口，不替代物理求解、阈值门禁和工程复核。"
        ),
        "本说明书用于介绍": (
            f"本说明书用于介绍{SOFTWARE_NAME} V1.0的开发目的、运行环境、系统架构、核心数据、关键基础设施模块、"
            "爆炸场景建模、求解型模型生成、多级验证、智能毁伤评估和操作方法，为软件著作权登记、软件交付及后续维护"
            "提供统一文档依据。"
        ),
        "文档面向软件著作权": (
            "文档面向软件著作权登记审查人员、软件使用人员、项目维护人员和工程复核人员。界面、模块、字段和证据以"
            "当前项目源代码、本地工作台及2026年8月25日前形成的实现和验证记录为依据。"
        ),
        "商业超市、住宅建筑和地铁入口三类": (
            "住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊、加油站等城市关键基础设施模块的选择、"
            "参数配置、物理构件编译和场景组合。"
        ),
        "软件把精细建筑": (
            "软件把城市关键基础设施爆炸冲击模型准备、数值求解验证和毁伤评估组织为受控、可重复的本地工作流。用户"
            "通过工作台选择关键基础设施类型、结构体系和载荷提供器，填写Schema驱动参数，保存不可变项目修订，经软件"
            "门禁后生成K文件，并在授权条件下交给LS-PrePost或LS-DYNA。"
        ),
        "优化后的核心目标": (
            "系统核心目标是形成包含关键基础设施物理构件、可移动TNT、可见空气域、地面和真实FSI的依赖闭合model.k，"
            "把外部程序与求解证据绑定到模型身份，并依据可信结果指标和适用毁伤判据自动形成对象级毁伤风险等级及可追溯"
            "评估报告。"
        ),
        "三类参数化精细建筑": (
            "住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等参数化关键基础设施模块及多种结构体系。"
        ),
        "重要：Solver-Complete": (
            "重要：Solver-Complete表示关键字依赖闭合且已经通过指定流程验证，不表示可直接用于真实工程设计。智能毁伤评估"
            "仅在求解质量、对象级指标和阈值来源同时通过门禁后输出等级；缺少可信判据或证据时保持“无法评估”，不得以演示"
            "阈值替代工程认证。"
        ),
        "截至2026年8月21日": (
            "源程序由Python、JavaScript、HTML和CSS组成，覆盖关键基础设施建模、爆炸场景编译、结果来源核验、对象级指标"
            "提取、毁伤分级、报告生成和Web交互等模块。正式登记前应针对最终冻结版本重新统计源程序行数。"
        ),
        "系统采用本地Web工作台": (
            "系统采用本地Web工作台和Python后端服务相结合的分层结构。交互层负责关键基础设施、场景、验证和评估操作；"
            "项目服务层负责修订、能力匹配、生成和存储；领域编译层负责设施物理模型、爆炸配置、ALE场景和关键字写出；"
            "验证与智能评估层负责物理审计、外部程序验证、结果来源核验、对象级指标提取、毁伤判据匹配、等级判定和证据报告。"
        ),
        "用户输入经闭合Schema": (
            "用户输入经闭合Schema规范化后，系统先重建并核对关键基础设施工件，再编译物理模型；随后构造TNT、空气域、"
            "地面和FSI场景，写出依赖闭合model.k。模型依次通过静态重解析、LS-PrePost导入、R12模型检查和求解验证；结果"
            "文件经来源与哈希核验后提取对象级物理响应，匹配受控毁伤判据，生成毁伤风险等级、判定依据和不可变评估报告。"
        ),
        "前端工作台以八个配置步骤": (
            "前端工作台以设施、结构、连接、构件、材料、网格、爆源和检查等步骤组织建模，并提供求解结果与智能评估视图。"
            "右侧参数面板由后端Provider Schema动态生成，中央区域提供分层三维预览、视角控制、图层控制、对象响应和毁伤等级"
            "显示；评估结果可定位至具体设施、构件或部件。"
        ),
        "后端将精细建筑": (
            "后端将关键基础设施建模、精细爆炸、求解型编译和毁伤评估实现为相互隔离的领域模块。refined_building负责设施"
            "类型、拓扑、网格和构件语义；solver_blast负责物理模型、爆源、空气域、地面、材料、FSI、关键字和结果验证；"
            "city_result_source负责求解结果登记与证据核验；city_impact负责对象级指标、阈值门禁、毁伤风险分级及报告生成；"
            "web适配层提供API、存储事务和受控外部动作。"
        ),
        "验证执行层不信任": (
            "验证与评估执行层不信任生成时的内存对象，也不接受未登记的结果目录。系统重新读取model.k、model.json、d3hsp、"
            "dbfsi、glstat、elout、nodout和d3plot等文件，核验模型哈希、运行身份、文件连续性和结果完整性，再提取对象级指标。"
            "验证记录和评估结论均独立保存，不反向修改模型。"
        ),
        "RefinedBlastProject是": (
            "RefinedBlastProject是关键基础设施爆炸项目根对象，记录项目标识、设施引用、设施指纹、预设、项目覆盖、场景集合、"
            "来源、确认记录和修订号。所有保存操作使用预期修订比较并交换，防止并发覆盖。"
        ),
        "PhysicalBuilding保存": (
            "PhysicalBuilding为内部物理模型类名，保存按关键基础设施对象确定的节点、单元、构件记录、接口记录、材料角色、"
            "包围盒和流体暴露面。构件记录包含物理角色、单元族、尺寸、选择依据、连接标识和流体暴露状态；接口记录包含"
            "连接类型、共享节点、接触尺度、间隙、容差和两侧单元数量。"
        ),
        "SolverBlastCompilation同时返回": (
            "SolverBlastCompilation返回写出证据和静态验证报告；CityImpactAssessment在可信求解结果基础上返回对象级指标、"
            "响应验收、异常项、阈值档案状态、毁伤风险等级及判定依据。评估结果与model.k哈希、设施布局指纹、编辑状态指纹、"
            "材料契约和结果证据摘要绑定。"
        ),
        "Web生成包当前以model.k": (
            "Web生成包以model.k和model.json为核心文件，清单记录设施工件指纹、Provider输入指纹、场景指纹、模型哈希、"
            "节点与单元计数、ALE计数、FSI面数、爆源位置和状态声明；求解后可追加结果来源记录、对象级指标文件、智能评估JSON"
            "及HTML报告。"
        ),
        "系统针对共享节点": (
            "系统针对共享节点、正接触面积、接触长度、嵌入连接、最大间隙和连接容差生成审计记录。基础至竖向构件、竖向构件"
            "至楼盖、桥面、站厅、管廊顶板或设备支承等传力路径必须连续；同一物理角色不能同时输出多种单元族，连接两侧必须"
            "具有正单元数量。"
        ),
        "外部空气FSI只作用于": (
            "外部空气FSI只作用于外部可达表面。系统结合设施拓扑识别建筑外表面、桥梁构件、道路表面、站房与地铁出入口、"
            "管廊围护及加油站设备表面；被土体、围护或相邻构件遮蔽的内部表面不直接发布为空气耦合面。"
        ),
        "solver_complete_ale_fsi根据建筑": (
            "solver_complete_ale_fsi根据关键基础设施拓扑包围盒、地面高程、爆源坐标和空气域边距生成多材料ALE域。TNT通过"
            "等效质量和密度换算为球体并采用体积分数几何初始化，爆源位置可在三维范围内修改。"
        ),
        "系统为三类建筑生成": (
            "系统按关键基础设施类型生成地面或支承对象，并建立设施与地面、桥墩与基础、管廊与土体等连接或接触。空气域"
            "远边界采用非反射边界；设施和地面采用受控的Lagrange-in-solid流固耦合，写出前检查耦合面唯一性、初始穿透、"
            "爆源包含和空气体积分数。"
        ),
        "写出器按稳定顺序": (
            "写出器按稳定顺序输出控制与数据库、材料与状态方程、关键基础设施节点与单元、地面、ALE空气域、TNT初始化、"
            "边界、接触和流固耦合。相同设施工件、配置和程序版本生成相同模型语义与内容哈希。"
        ),
        "系统使用生成前物理审计": (
            "系统使用生成前物理审计、静态重解析、外部程序验证、求解结果验收和智能毁伤评估五个层级。任一阻断错误均停止"
            "后续阶段；只有求解质量、对象级指标和阈值来源同时通过门禁，系统才输出毁伤风险等级。"
        ),
        "短时求解完成后": (
            "求解完成后，结果解析器检查正常终止、时间覆盖率、负体积、NaN/Inf、总能量和沙漏能量，并从dbfsi、elout、nodout"
            "等结果提取峰值压力、正压力冲量、主应力峰值、最大位移、材料损伤指标、FSI到达时间和结构响应到达时间。系统按"
            "设施类别加载经过复核或用户确认的毁伤阈值档案，对每个语义对象执行分级判定。"
        ),
        "三类模型均实际通过": (
            "当前已有验证证据的商场示例、住宅和地铁入口模型均实际通过LS-PrePost导入和R12 mcheck，并在串行计算中正常终止。"
            "其他关键基础设施模块采用相同建模、编译、验证和评估接口，工程使用时应针对相应构造、材料和毁伤判据补充专项证据。"
        ),
        "工作台左侧为八步导航": (
            "工作台左侧为建模步骤导航，中间为分层三维预览，右侧为当前步骤参数、检查结果和对象级毁伤信息，底部提供保存草稿、"
            "刷新预览、验证、生成K包、登记求解结果和生成评估报告等操作。"
        ),
        "在建筑资产中选择": (
            "在关键基础设施模块中选择住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊或加油站，并选择相应设施模板。"
        ),
        "点击“保存草稿”": "点击“保存草稿”，首次保存创建独立关键基础设施项目并取得修订号。",
        "验证门禁允许后点击": (
            "验证门禁允许后点击“生成K包”，系统生成不可变model.k并返回包指纹；完成求解后登记结果目录，系统核验结果来源并"
            "自动生成对象级指标和毁伤评估报告。"
        ),
        "求解完成后使用验证脚本": (
            "求解完成后登记运行结果，系统收集运行ID、日志、glstat、dbfsi、elout、nodout和d3plot证据，提取对象级响应指标，"
            "匹配适用毁伤判据并输出毁伤风险等级、判定依据和评估报告。"
        ),
        "系统分别计算建筑工件": (
            "系统分别计算设施工件、Provider输入、场景、model.k、model.json、manifest和项目包指纹。求解验证另记录求解器"
            "可执行文件哈希、运行ID、结果文件身份和证据摘要；智能评估继续绑定阈值档案、材料契约和评估报告摘要。"
        ),
        "任一配置、资源、代码版本": (
            "任一配置、设施资源、代码版本、模型文件、结果文件或毁伤判据变化均产生新证据身份。旧修订、失败运行、正式候选"
            "快照和历史评估报告均保留，不允许通过覆盖旧目录制造新的通过结果或等级结论。"
        ),
        "本地API限制请求方法": (
            "本地API限制请求方法、内容类型、请求大小和同源访问。外部动作凭证与具体动作及模型身份绑定，具有有效期且只能"
            "使用一次；绝对路径、目录穿越、未知字段、陈旧修订、文件哈希不一致、未登记结果和未受信任阈值均被拒绝。"
        ),
        "使用限制：当前1 ms": (
            "使用限制：现有1 ms示例求解主要用于验证初始化、传播起始和数值稳定性，不能单独代表完整毁伤过程。智能评估模块"
            "能够处理完整求解结果并依据受控判据分级，但结论质量取决于材料标定、网格与时程收敛、结果完整性和阈值适用性。"
        ),
        "大语言模型爆炸工况评估": (
            "大语言模型接口属于后续扩展方向，可用于解释对象级指标、毁伤等级及证据来源；物理指标提取、判据匹配和等级确定仍"
            "由确定性程序完成，大语言模型不直接修改K文件，也不越过证据门禁输出工程认证结论。"
        ),
        "面向精细建筑结构爆炸冲击分析": (
            "面向城市关键基础设施爆炸冲击分析，提供设施模块、物理构件、爆炸场景、求解型K文件、程序验证、对象级响应指标、"
            "毁伤判据、智能分级、评估报告和项目版本管理的一体化本地软件，降低重复建模、引用缺失、物理关系不一致及结论"
            "来源不清等风险。"
        ),
        "软件支持三类精细建筑": (
            "软件支持住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊、加油站等城市关键基础设施模块和多种"
            "结构体系；支持构件单元族选择、连接与传力路径审计；支持可移动TNT、多材料ALE空气域、地面、材料状态方程和真实"
            "FSI；支持model.k确定性生成、静态重解析、LS-PrePost导入、LS-DYNA检查与求解；支持结果证据核验、对象级物理指标"
            "提取、毁伤判据匹配、风险等级判定、异常识别以及JSON和HTML评估报告输出。"
        ),
        "软件采用精细建筑语义工件": (
            "软件采用关键基础设施语义工件、物理构件编译、闭合配置契约、求解型ALE/FSI场景、固定次序关键字写出、多级外部"
            "验证、对象级响应解析、受控毁伤判据、智能分级和不可变证据绑定等技术，实现设施输入、生成文件、求解记录、毁伤"
            "等级和评估依据的一致管理。"
        ),
    }
    for prefix, text in targeted.items():
        set_paragraph_text(find_paragraph(doc, prefix), text)

    heading_replacements = {
        "5.3 PhysicalBuilding": "5.3 PhysicalBuilding（关键基础设施物理模型）",
        "5.5 SolverBlastCompilation与ValidationReport": "5.5 编译、验证与智能评估数据",
        "6 精细建筑物理建模": "6 城市关键基础设施物理建模",
        "6.1 支持的资产": "6.1 支持的关键基础设施",
        "9 校验、求解与结果证据": "9 校验、求解与智能毁伤评估",
        "9.1 四级验证": "9.1 分级验证与评估门禁",
        "9.4 短时求解与结果解析": "9.4 求解结果解析与智能毁伤评估",
        "9.5 三类模型验收结果": "9.5 当前模型验收结果",
        "10.3 选择建筑资产": "10.3 选择关键基础设施",
        "10.5 保存、验证与生成": "10.5 保存、验证、生成与评估",
    }
    for old, new in heading_replacements.items():
        for paragraph in doc.paragraphs:
            if paragraph.text.strip() == old:
                set_paragraph_text(paragraph, new)

    anchor = find_paragraph(doc, "求解完成后，结果解析器检查")
    assessment_bullets = [
        "证据门禁：确认求解正常终止、结果时程覆盖充分、必需输出文件完整、模型与结果哈希一致，并验证每个评估对象均有独立响应数据。",
        "指标推理：按语义对象提取峰值压力、冲量、应力、位移、材料损伤和到达时间，识别异常位移、响应缺失及数值异常。",
        "判据匹配：依据设施类别、材料契约和适用范围加载经复核或用户确认的阈值档案，按照最不利适用指标确定“低、关注、较高、严重”四级毁伤风险；证据不足时输出“无法评估”。",
        "结果表达：形成对象、部件和整体场景的等级、触发指标、阈值来源、工程提示及证据摘要，并输出city_impact_assessment.json和city_impact_report.html。",
    ]
    for bullet in assessment_bullets:
        anchor = insert_paragraph_after(anchor, bullet, "List Bullet")

    technical_feature_prefixes = [
        "精细建筑语义工件与求解物理模型分层",
        "构件物理属性驱动单元族选择",
        "闭合SolverBlastConfig避免",
        "真实TNT、空气域、地面和FSI生成链",
        "固定关键字顺序、目标版本数值格式",
        "LS-PrePost、mcheck、短时求解和传播判据",
        "模型、程序、运行和结果指纹",
        "外部动作独立授权",
    ]
    technical_features = [
        "城市关键基础设施类型模块与求解物理模型分层，可在统一接口下组织住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等设施。",
        "构件物理属性驱动Solid、Shell和Beam单元族选择，并通过连接接口证据验证传力连续性。",
        "闭合SolverBlastConfig和Provider能力声明共同约束单位、爆源、空气域、边界、材料及输出请求，减少参数漂移。",
        "可移动TNT、多材料ALE空气域、地面和真实FSI组成求解型场景生成链。",
        "固定关键字顺序、目标版本数值格式、依赖闭合重解析和原子发布保证生成结果确定且可追溯。",
        "LS-PrePost、mcheck、求解质量、对象响应完整性和阈值来源组成递进式就绪门禁。",
        "自动提取压力、冲量、应力、位移和材料损伤等物理指标，并依据适用毁伤判据生成分级结果。",
        "模型、程序、运行、结果、阈值档案和评估报告共同形成不可变证据身份，支持结论追溯和复核。",
    ]
    for prefix, text in zip(technical_feature_prefixes, technical_features, strict=True):
        set_paragraph_text(find_paragraph(doc, prefix), text)

    source_tree = find_paragraph(doc, "lsprepost_mcp/")
    set_paragraph_text(
        source_tree,
        "lsprepost_mcp/\n"
        "  refined_building/                         # 关键基础设施资源、拓扑和构件编译\n"
        "    assets/                                 # 设施类型与参数化模板\n"
        "    backends/                               # RC、钢结构、混合结构和箱体等后端\n"
        "    asset_compiler.py                       # 设施物理工件编译\n"
        "    solver_validation.py                    # 设施求解验证\n"
        "    solver_blast/                           # TNT、ALE、地面、材料、FSI和关键字\n"
        "      results.py                            # 能量、传播和结果证据\n"
        "  refined_blast/                            # 项目、Provider、修订、门禁和证据\n"
        "  city_result_source.py                     # 城市求解结果登记与证据核验\n"
        "  city_impact.py                            # 对象级指标、阈值匹配、毁伤分级与报告\n"
        "  city_ground_crater_acceptance.py          # 地面响应与爆坑证据验收\n"
        "  solver_results.py                         # DBFSI、ELOUT、NODOUT结果解析\n"
        "  web/                                      # Web API、工作台状态与交互\n"
        "scripts/                                    # 模型生成、导入和求解验证脚本"
    )

    # Table 0: document information.
    table = doc.tables[0]
    set_cell_text(table.cell(1, 1), SOFTWARE_SHORT_NAME)
    set_cell_text(table.cell(4, 1), "2026年8月25日")

    # Table 1: title and category.
    table = doc.tables[1]
    set_cell_text(table.cell(1, 1), f"{SOFTWARE_NAME} V1.0 软件设计与操作说明书")
    set_cell_text(table.cell(4, 1), "工程分析与智能评估软件 / 有限元前处理、求解型模型生成、结果解析与毁伤分级软件")

    # Table 2: version history.
    table = doc.tables[2]
    append_styled_row(table, ["V1.0 城市关键基础设施与智能评估适配稿", "2026-08-25", "[待填写]", "扩展关键基础设施模块，增加对象级指标、毁伤判据、分级评估与报告功能说明"])

    # Table 3: terminology.
    table = doc.tables[3]
    set_cell_text(table.cell(4, 0), "PhysicalBuilding")
    set_cell_text(table.cell(4, 1), "内部物理模型类名，由关键基础设施工件编译得到构件、连接和外露表面集合。")
    append_styled_row(table, ["毁伤判据档案", "按设施类别和物理指标组织的受控阈值集合，必须记录来源、状态、适用范围及模型和材料绑定信息。"])
    append_styled_row(table, ["智能毁伤评估", "对可信求解结果自动完成对象识别、指标提取、判据匹配、等级确定、异常提示和报告生成。"])

    # Table 7: supported infrastructure modules.
    table = doc.tables[7]
    set_cell_text(table.cell(0, 0), "关键基础设施模块")
    set_cell_text(table.cell(0, 1), "主要物理组成")
    set_cell_text(table.cell(0, 2), "建模与评估用途")
    module_rows = [
        ["住宅", "基础、柱、梁、剪力墙、楼板、外墙、钢筋及非承重构件", "爆炸冲击建模、构件响应与整体毁伤评估"],
        ["商场", "基础、楼板、实体围护、大跨梁柱、钢屋面、入口框架及玻璃", "外部爆炸ALE/FSI及人员密集空间设施评估"],
        ["工厂", "工业厂房框架、屋架、围护、设备基础、管线和附属构件", "厂房结构与关键设备区域爆炸毁伤评估"],
        ["医院", "门诊与住院建筑、连廊、设备层、围护和关键功能房间", "医疗设施构件响应与功能影响辅助评估"],
        ["火车站", "站房、站厅、站台、雨棚、连廊、轨道邻近构件和设备区", "交通枢纽爆炸冲击与关键区域评估"],
        ["道路", "路面、基层、路基、中央隔离、护栏及附属设施", "道路表面、地基响应和通行影响辅助评估"],
        ["高架桥", "桥墩、盖梁、主梁、桥面、支座、防撞护栏和基础", "桥梁关键构件响应、支承状态与毁伤分级"],
        ["地铁", "出入口、站厅、站台、地下箱体、隧道、楼梯和设备构件", "地下及半封闭设施爆炸场景与对象级评估"],
        ["综合管廊", "廊体、隔墙、顶底板、管线、支架、节点舱和出入口", "围护结构、管线支承及功能影响辅助评估"],
        ["加油站", "罩棚、立柱、加油设备、储罐、管路、站房和围护", "能源设施爆炸场景、关键部件与区域风险评估"],
    ]
    # Reuse the three existing rows, then append the remainder.
    for row, values in zip(table.rows[1:4], module_rows[:3], strict=True):
        for cell, value in zip(row.cells, values, strict=True):
            set_cell_text(cell, value)
    for values in module_rows[3:]:
        append_styled_row(table, values)

    # Table 11 and 12 contain actual evidence for three validated examples.
    set_cell_text(doc.tables[11].cell(0, 0), "已验证模型")
    set_cell_text(doc.tables[11].cell(1, 0), "商场示例")
    set_cell_text(doc.tables[12].cell(0, 0), "已验证模型")
    set_cell_text(doc.tables[12].cell(1, 0), "商场示例")

    # Table 14: software registration information.
    table = doc.tables[14]
    set_cell_text(table.cell(1, 1), f"{SOFTWARE_NAME} V1.0")
    set_cell_text(table.cell(2, 1), SOFTWARE_SHORT_NAME)

    # Final Chinese terminology pass. Internal code identifiers are intentionally retained.
    for paragraph in doc.paragraphs:
        replace_text_in_paragraph(paragraph, "建筑资产", "关键基础设施")
        replace_text_in_paragraph(paragraph, "资产指纹", "设施指纹")
        replace_text_in_paragraph(paragraph, "资产", "设施")
        replace_text_in_paragraph(paragraph, "三类建筑", "当前三类已验证设施")
        replace_text_in_paragraph(paragraph, "物理建筑", "设施物理模型")
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    replace_text_in_paragraph(paragraph, "建筑资产", "关键基础设施")
                    replace_text_in_paragraph(paragraph, "资产指纹", "设施指纹")
                    replace_text_in_paragraph(paragraph, "资产", "设施")
                    replace_text_in_paragraph(paragraph, "物理建筑", "设施物理模型")

    doc.core_properties.title = f"{SOFTWARE_NAME} V1.0 软件设计与操作说明书"
    doc.core_properties.subject = "软件著作权登记材料"
    doc.core_properties.keywords = "城市关键基础设施,爆炸毁伤,有限元,LS-DYNA,智能评估"
    enable_field_updates(doc)
    destination.parent.mkdir(parents=True, exist_ok=True)
    doc.save(destination)


if __name__ == "__main__":
    rewrite(Path(sys.argv[1]), Path(sys.argv[2]))
