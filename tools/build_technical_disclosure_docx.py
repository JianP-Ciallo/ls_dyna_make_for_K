from __future__ import annotations

import argparse
import shutil
from pathlib import Path

try:
    from .work_paths import existing_input
except ImportError:  # Direct script invocation.
    from work_paths import existing_input

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = existing_input("technical_disclosure_work", "figures")
SCREENSHOT_DIR = existing_input("soft_copyright_work", "runtime_screens_refined")
IMPACT_SCREENSHOT = existing_input("soft_copyright_work", "runtime_screens_actual", "09-actual-model-impact.png")

TITLE = "一种面向城市关键基础设施爆炸毁伤的精细化建模与智能评估方法及系统"


TECHNICAL_FIELD = [
    "本发明涉及爆炸力学、结构工程、计算机辅助工程、非线性有限元分析、工程软件自动化及计算机智能评估技术领域，尤其涉及一种面向城市关键基础设施爆炸毁伤的精细化建模、受控关键字文件生成、物理响应证据提取和毁伤等级评估方法及系统。",
    "本发明可用于住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等城市关键基础设施的爆炸冲击工况建模与评估。其中，设施类型通过版本化资源和能力声明接入；已完成求解链验证的具体实施例包括商业建筑、住宅建筑和地铁入口。",
]


BACKGROUND = [
    ("一、行业与技术背景", [
        "爆炸冲击作用具有持续时间短、压力梯度大、材料应变率效应显著以及结构与空气相互作用复杂等特点。采用非线性有限元方法开展爆炸毁伤研究时，通常需要同时描述关键基础设施的几何和承重体系、炸药及空气域、材料本构与失效、接触与边界、流固耦合、求解控制和结果输出。LS-DYNA等显式动力学软件能够处理上述大变形、材料非线性和强瞬态问题，但其关键字模型依赖关系多、参数物理含义复杂，且同一工况需要在几何、网格、材料、载荷和求解控制之间保持严格一致。",
        "在实际工程和科研教学中，模型通常由工程人员在前处理软件中逐项建立，或基于历史关键字文件修改。该方式对关键字语法、单位制、材料模型、空气域尺寸、爆源位置、边界反射、流固耦合面和求解器版本均有较高经验要求。对于商业建筑、住宅、地铁入口等设施，实体、壳和梁单元往往混合使用，钢筋与混凝土之间还需建立嵌入或约束关系，使模型准备、复核和版本管理耗时较长。",
    ]),
    ("二、需要解决的技术问题", [
        "现有模板化建模工具通常只能生成少量固定场景，难以证明所选模板、构件资源和材料参数与当前设施及爆炸工况相匹配；通用脚本虽然能够减少重复操作，但容易出现单位制不一致、部件编号冲突、引用缺失、空气域或地面网格不合理、炸药质量与几何不一致、流固耦合面错误以及输出请求不完整等问题。模型可以被软件打开并不等同于物理关系正确，也不等同于能够稳定求解或具备工程可信度。",
        "若允许大语言模型直接生成任意有限元关键字文件，还可能出现不存在的关键字卡片、字段含义误判、参数来源不明、错误结果被自然语言包装为确定结论等风险。另一方面，传统评估流程常由人工从结果文件中读取峰值压力、冲量、应力、位移和材料损伤等指标，再依据经验或分散表格判断毁伤等级，模型、求解结果、阈值来源和最终结论之间缺乏稳定的可追溯关系。",
    ]),
    ("三、现有解决方式及不足", [
        "已有方法主要包括人工前处理、历史模型复制、参数化脚本、固定场景模板以及基于自然语言的代码或关键字生成。人工和复制方式效率低、复核工作量大；参数化脚本和固定模板对超出预设范围的设施及结构体系适应性有限；直接生成方式缺少受控中间表示、能力边界、确定性编译和结果证据门禁，难以区分软件检查通过、求解器实际运行、结果完整性检查和工程人员审核四种不同状态。",
        "因此，需要一种以物理模型和确定性程序为执行主体、以能力声明限定输入范围、以分级校验控制生成和评估、以不可变证据绑定模型与结论的技术方案。同时，需要限定大语言模型的作用，使其仅负责理解需求、补充信息和提出受控工具调用建议，而不能绕过确定性编译器直接写入关键字文件或擅自提升工程验证等级。",
    ]),
]


TECHNICAL_SOLUTION = [
    ("一、发明目的", [
        "本发明旨在解决城市关键基础设施爆炸冲击有限元模型准备过程中输入语义不统一、物理配置容易失配、关键字文件难以稳定复现、模型生成和毁伤评估缺乏分级门禁、模型与评估结论来源难以追溯以及大语言模型直接生成工程文件风险较高等问题。",
        "本发明通过受控场景中间表示、设施资源和能力声明、确定性物理模型编译器、多级校验门禁、对象级物理响应提取、受控毁伤判据匹配和不可变证据链，将项目输入、有限元模型、外部求解结果和评估报告组织为可复核的完整技术流程。",
    ]),
    ("二、术语和数据对象", [
        "1. 城市关键基础设施：指在城市运行、公共服务或人员安全中具有重要作用的建筑物、构筑物和工程设施。设施类型可包括住宅、商场、工厂、医院、火车站、道路、高架桥、地铁、综合管廊和加油站等。每一设施类型通过设施资源工件描述其空间、构件、结构体系、接口、材料角色和适用范围。",
        "2. 受控场景中间表示：指位于用户输入与有限元关键字编译器之间的结构化数据对象。该对象至少包括项目标识、设施类型、结构体系、单位制、几何与构件、材料和连接、爆源、空气域、地面、边界、耦合、求解控制、输出请求、字段来源、假设项、待确认项及审核状态。",
        "3. 能力声明：指以版本化数据形式声明某设施资源、结构后端、载荷提供器、材料资源和外部程序能够接受的字段、数值范围、单位、依赖条件、规模预算及程序版本。能力声明不满足时，系统执行追问、拒绝或转人工复核，而不是自动扩展模型能力。",
        "4. 确定性编译：指相同规范化输入、相同资源版本和相同编译器版本产生相同关键字顺序、数值格式、依赖闭包和模型包指纹的生成过程。",
        "5. 不可变证据：指与项目修订绑定的模型文件、配置快照、资源版本、程序身份、运行标识、结果文件、物理指标、判据档案和评估报告摘要。任一组成发生变化时形成新的证据身份，旧结果不得覆盖。",
    ]),
    ("三、方法流程", [
        "如图1所示，本发明的方法包括步骤S101至步骤S110。",
        "S101，接收项目、爆炸工况和评估目标。系统接收用户上传或选择的设施资源、结构体系、几何参数、材料与连接信息、炸药类型及当量、爆源位置、求解控制、期望输出和审核等级；对于缺失或冲突字段保留来源状态，不以默认值掩盖未知工程条件。",
        "S102，对输入进行受控解析和单位规范化。系统根据字段模式执行类型、范围、枚举、数组规模和标识符检查，将长度、时间、质量、力和压力等量统一到选定的规范单位制。设输入数值为x、单位转换比例为a_u、偏移量为b_u，则规范值满足：",
        "FORMULA:x_SI = a_u × x + b_u                         （1）",
        "规范化同时记录原始值、原始单位、转换规则和数据来源；来源不明的材料或毁伤参数只能标记为待确认，不能作为已审核参数。",
        "S103，构建受控场景中间表示。系统将设施、结构、爆源和输出要求组织为闭合数据合同，并分别记录已知字段、假设字段、缺失字段和冲突字段。场景中间表示与最终关键字文件解耦，使自然语言、界面表单和外部项目均通过同一语义层进入编译过程。",
        "S104，执行设施模板和能力声明匹配。系统根据设施类型、结构体系、载荷方式、目标求解器和输出要求选择设施资源、结构后端和载荷提供器。匹配条件至少包括资源状态、版本兼容、允许的单元族、材料角色、空气域能力、耦合方式、单位制、网格规模和外部程序版本。若关键字段不完整或能力不满足，则输出可定位的缺失项和纠正建议。",
        "S105，编译设施结构、材料、连接和网格。设施资源首先生成独立的几何与拓扑工件，再由物理编译器依据构件角色选择实体单元、壳单元或梁单元；建立混凝土、钢材、玻璃和非结构构件对应的材料及截面；建立钢筋嵌入、构件连接、接触、支承和边界；随后依据全局尺寸、局部加密区域和规模预算生成结构网格。",
        "S106，配置爆源、ALE空气域、地面和FSI关系。对于显式多材料ALE实施方式，根据炸药质量m_e和密度ρ_e计算等效球形装药半径r_e：",
        "FORMULA:r_e = [3m_e / (4πρ_e)]^(1/3)               （2）",
        "系统将装药体置于空气域内，建立空气和炸药初始体积分数、空气域外边界、地面支承和结构外表面流固耦合关系。流固耦合面由结构外部可接触表面集合生成，内部封闭面、重复面和非暴露面被排除。空气网格和地面网格分别受能力范围及规模预算约束。",
        "S107，确定性生成关键字文件包。如图4所示，系统按照控制卡、数据库、节点、单元、部件、材料、状态方程、截面、ALE域、炸药初始化、边界、接触、约束、耦合和输出的固定顺序写入文件；在写入前执行部件、材料、截面、曲线和集合标识符的统一分配，闭合所有引用依赖，并使用目标版本的数值格式。生成文件先写入临时目录，完成重新解析和指纹校验后再原子发布。模型包指纹可表示为：",
        "FORMULA:F_pkg = SHA-256[C(P) ∥ C(S) ∥ C(R) ∥ H(K) ∥ V_c]     （3）",
        "其中，C(P)为项目规范化表示，C(S)为场景规范化表示，C(R)为资源及版本规范化表示，H(K)为关键字文件摘要，V_c为编译器版本。",
        "S108，执行多级校验和就绪门禁。如图6所示，校验至少包括结构化输入校验、物理与依赖校验、网格及预算校验、关键字静态校验、外部前处理导入校验、求解初始化或求解质量校验以及结果证据校验。错误必须修正；警告必须与当前项目修订、校验指纹和警告内容哈希绑定确认。生成门可表示为：",
        "FORMULA:G_gen = P_saved ∧ V_current ∧ (E = ∅) ∧ (W ⊆ A) ∧ B_ok     （4）",
        "其中，P_saved表示当前草稿已持久化，V_current表示校验对应当前修订，E为阻断错误集合，W为警告集合，A为已确认警告集合，B_ok表示规模与资源预算满足要求。",
        "S109，从求解结果中提取对象级物理响应。系统先校验求解器身份、运行标识、模型摘要、结果文件身份、终止状态和时间覆盖，再依据设施、区域和构件到有限元部件、单元集合和历史节点的映射，提取峰值压力、正相冲量、结构应力、应变、位移、材料损伤和流固耦合到达时间等指标。对于对象o，其正相冲量可按下式计算：",
        "FORMULA:J_o = ∫[t0,t1] max[p_o(t) - p_0, 0] dt        （5）",
        "其中，p_o(t)为对象监测位置的压力时程，p_0为环境基准压力，t0和t1为证据覆盖范围内的积分起止时刻。",
        "S110，执行受控毁伤判据匹配并生成评估报告。系统根据设施类别、构件角色、材料、指标单位和适用范围选择状态为已复核或用户确认的阈值档案；将对象指标与关注、较高和严重阈值比较，采用最不利适用指标确定对象等级。若指标、单位、材料合同、结果时长、对象映射或阈值来源不满足要求，则输出“无法评估”及具体原因，而不生成确定性等级。对象等级可表示为：",
        "FORMULA:L_o = max_j Q(x_o,j ; θ_c,j)                 （6）",
        "其中，x_o,j为对象o的第j项物理指标，θ_c,j为适用于对象类别c和指标j的分级阈值，Q为返回低、关注、较高或严重等级的分段判定函数。",
    ]),
    ("四、系统组成", [
        "如图2所示，本发明的系统至少包括：项目与工况接收模块、受控请求解析模块、场景中间表示模块、设施资源与能力声明模块、确定性物理模型编译模块、爆源及ALE/FSI配置模块、关键字文件生成模块、校验与就绪门禁模块、结果证据解析模块、毁伤判据评估模块以及不可变项目与证据存储模块。",
        "系统可以部署在本地计算机、局域网服务器或工程计算节点上。各模块通过闭合的数据合同交换数据；模型生成模块不读取自然语言，毁伤判定模块不读取未经登记的结果文件，大语言模型适配器不直接访问文件系统和外部求解进程。",
    ]),
    ("五、可选的大语言模型受控编排实施方式", [
        "如图8所示，在可选实施方式中，用户将关键基础设施项目、爆炸目标和已有参数资料提交给大语言模型适配器。适配器仅输出结构化字段候选、缺失信息问题和工具调用建议；确定性控制器对候选内容执行模式校验、能力匹配、权限检查、审批检查、幂等检查和状态转换。通过检查后，受控工具网关才调用既有建模、预览、验证、生成或结果读取工具。",
        "大语言模型不得直接生成、编辑或覆盖有限元关键字文件，不得自行采用未审核材料或毁伤阈值，不得直接启动外部程序，也不得将软件校验通过解释为求解验证或工程审核通过。高风险动作必须由用户确认；工具失败或校验发现返回大语言模型时，大语言模型只能提出修正候选，最终执行仍由确定性控制器决定。",
        "该实施方式使语言理解与工程执行相分离：模型平面负责提出候选，控制平面负责状态、政策和审批，执行平面负责确定性工具及证据生成。即使关闭大语言模型功能，用户仍可通过原工作台完成同一确定性建模和评估流程。",
    ]),
    ("六、建议重点保护的区别技术特征", [
        "1. 用户项目和爆炸工况先转换为带来源、假设和待确认状态的受控场景中间表示，再进入有限元模型编译器，而不是直接拼接关键字文本。",
        "2. 设施资源、结构后端、载荷提供器和外部程序均以能力声明限定适用范围，超出范围时追问、拒绝或转人工复核。",
        "3. 结构、材料、网格、TNT、ALE空气域、地面、边界及FSI关系由确定性编译链统一生成，并以依赖闭包、固定顺序、目标版本格式和原子发布保证复现性。",
        "4. 生成、外部程序交接和毁伤评估分别受当前项目修订、校验指纹、警告确认、程序身份和结果证据约束，任一输入变化均使旧派生结果失效。",
        "5. 毁伤评估以对象级物理响应和有来源、有版本、有适用范围的阈值档案为依据，证据不完整时明确返回无法评估。",
        "6. 可选大语言模型仅提出结构化候选和工具调用建议，确定性控制器保留工程文件写入、外部程序启动和毁伤等级输出的最终控制权。",
    ]),
    ("七、替代实施方式", [
        "爆炸载荷可采用多材料ALE与流固耦合、拉格朗日爆炸载荷面、经审核的压力时程导入或其他具有明确适用范围的载荷提供器；有限元求解器可为支持相应显式动力学、材料和耦合能力的软件。摘要算法可采用SHA-256或满足完整性要求的其他密码摘要算法。大语言模型可以由不同供应商模型实现，但必须通过同一结构化接口和确定性控制器。上述替代不改变受控中间表示、能力匹配、确定性编译、分级门禁和证据绑定的核心技术关系。",
    ]),
]


BENEFITS = [
    "1. 具有明确物理依据。结构单元角色、材料、TNT装药、ALE空气域、地面、边界和FSI关系均由物理配置和设施资源驱动，而非由文本模型自由编造。",
    "2. 提高模型生成的一致性和可复现性。相同规范化输入、资源和编译器版本得到相同依赖闭包、关键字顺序及模型包指纹，便于比较不同方案。",
    "3. 降低单位、引用和模型关系错误。能力声明、闭合数据合同、统一标识符分配和重新解析检查能够在外部求解前发现大量可定位问题。",
    "4. 区分软件通过、求解执行、结果检查和工程审核。分级门禁避免把浏览器预览、关键字可读取或短时求解误认为完整工程验证。",
    "5. 提高爆炸工况配置与复核效率。设施资源、结构后端和载荷提供器复用已审核模块，同时保留项目级参数、警告和人工确认记录。",
    "6. 提供可解释的智能毁伤评估。毁伤等级由对象级压力、冲量、应力、位移或材料损伤指标与受控阈值档案共同确定，并给出控制指标、阈值来源和无法评估原因。",
    "7. 实现全过程追溯。模型、参数、程序、运行、结果、指标、阈值和报告通过不可变修订及摘要关联，历史结果不被新运行覆盖。",
    "8. 限制大语言模型风险。大语言模型只负责语言理解和候选动作，工程执行权由确定性控制器和受控工具保留，可在不改变原建模内核的情况下增加智能交互能力。",
    "9. 具备扩展性。新增设施、结构体系、材料、载荷方法或求解程序时，只需增加相应资源、适配器和能力声明，无需改变核心证据和门禁机制。",
]


FIGURE_DESCRIPTIONS = [
    "图1为本发明实施例的整体处理流程图；",
    "图2为本发明实施例的系统模块结构图；",
    "图3为本发明实施例的受控请求解析、场景中间表示与能力匹配流程图；",
    "图4为本发明实施例的确定性物理模型编译与关键字文件生成流程图；",
    "图5为本发明实施例的ALE空气域、TNT装药及结构FSI耦合关系示意图；",
    "图6为本发明实施例的多级校验、警告确认与生成就绪门禁流程图；",
    "图7为本发明实施例的不可变项目修订与证据溯源关系图；",
    "图8为本发明实施例的可选大语言模型受控工具调用流程图；",
    "图9为本发明商业建筑精细爆炸模型工作台运行界面；",
    "图10为本发明地铁入口精细爆炸模型分层预览界面；",
    "图11为本发明对象级智能毁伤评估界面。",
]


EMBODIMENTS = [
    ("一、通用实施流程", [
        "本实施方式在Windows本地计算机上运行Web工作台和确定性建模服务，有限元目标格式为LS-DYNA关键字格式，规范单位制为m、s、kg、N、Pa。用户进入独立精细爆炸工作台后选择设施资源和允许的结构体系，系统从能力目录载入适用字段和默认载荷提供器。用户保存草稿后形成独立项目标识和修订号；设施类型或结构体系需要改变时创建新项目，防止不同资源身份混用。",
        "用户在爆源步骤设置TNT当量、爆源坐标、起爆时间、空气网格、空气边距、地面网格、终止时间和输出请求。系统对每次字段变更增加草稿修订，清除旧预览、旧校验和旧生成身份。用户刷新预览时，服务端针对当前持久化修订编译九层中性预览，包括空腔与洞口、主体结构、钢筋与连接、非承重构件、暴露面、爆源、流体域、边界以及支承与地面。",
        "用户执行验证后，界面显示错误、警告和信息。错误必须修改；警告经工程人员阅读后与当前修订绑定确认。仅当生成门通过时开放K包生成。生成包包含model.k、model.json、manifest.json、检查结果、配置快照和证据索引。打开LS-PrePost或启动求解器属于独立外部动作，需要一次性确认凭证，并再次核对项目、场景、修订和包指纹。",
    ]),
    ("二、实施例1：商业建筑精细爆炸模型", [
        "选择商业建筑详细资源和钢-混凝土组合结构体系。模型外墙采用实体单元，承重柱采用截面为0.30 m×0.30 m的钢筋混凝土实体柱，柱内设置纵向钢筋和闭合箍筋，外墙设置横向及竖向钢筋，并保留门洞净空；同时包含组合基础、组合楼板、非结构隔墙和钢屋面构件。图9示出商业建筑模型在工作台中的分层预览。",
        "示例公共工况采用2 kg TNT，爆源坐标为[-2.0，1.5，4.0] m，空气网格尺寸为0.40 m，地面网格尺寸为0.25 m，三个方向空气边距均为3.0 m，终止时间为0.001 s。装药位于ALE空气域内，结构外表面形成FSI从属段集合。生成模型包含158067个节点、127592个单元、71148个ALE单元和29330个FSI面。",
        "该模型经LS-DYNA R12模型检查完成初始化循环并正常终止；1 ms初步求解中空气响应到达时间为0.0003019 s，建筑响应到达时间为0.00095079 s。该证据用于证明关键字生成链、初始化、空气传播起始和结构响应可执行，不代表完整毁伤过程、网格收敛或工程审批。",
    ]),
    ("三、实施例2：住宅建筑精细爆炸模型", [
        "选择住宅建筑详细资源和钢筋混凝土结构体系。模型包括钢筋混凝土梁、柱、剪力墙、楼板和基础，并包含外墙、非结构隔墙和阳台护栏。钢筋与宿主实体采用经检查的嵌入关系，钢筋节点身份与宿主实体节点身份分离，避免梁单元与实体单元共享节点造成求解器初始化错误。",
        "采用与实施例1相同的2 kg TNT公共工况时，生成模型包含197624个节点、161002个单元、73568个ALE单元和48926个FSI面。经LS-DYNA R12检查后正常终止；1 ms初步求解中空气响应到达时间为0.00035082 s，建筑响应到达时间为0.00095088 s。",
    ]),
    ("四、实施例3：地铁入口精细爆炸模型", [
        "选择地铁入口详细资源和钢筋混凝土地下箱体结构体系。模型包括入口亭、玻璃幕墙、钢框架、实体屋面、钢筋混凝土基座、两组扶梯、固定楼梯、上下平台以及地下箱体底板、顶板和侧墙。根据构件物理角色，地下箱体和实体屋面采用实体单元，玻璃采用壳单元，钢框架采用梁单元，并通过明确连接关系组成混合结构。图10示出地铁入口模型及可选构件图层。",
        "采用2 kg TNT公共工况时，生成模型包含156314个节点、133722个单元、74592个ALE单元和10128个FSI面。经LS-DYNA R12检查后正常终止；1 ms初步求解中空气响应到达时间为0.00065046 s，建筑响应到达时间为0.00095029 s。",
    ]),
    ("五、实施例4：对象级毁伤评估", [
        "求解完成后，将运行标识、求解器摘要、模型摘要和结果文件登记到项目证据目录。系统检查结果文件是否与当前模型匹配、求解是否正常终止、时间覆盖是否满足评估要求、对象到部件和历史节点的映射是否完整，并从压力、冲量、应力、位移和材料损伤结果中形成对象级指标。",
        "系统读取受控阈值档案，阈值档案包含适用设施类别、构件角色、材料、指标、单位、关注阈值、较高阈值、严重阈值、来源、版本和审核状态。仅当阈值档案与对象类别及当前指标匹配时才执行分级。图11示出评估界面；界面能够显示对象列表、等级筛选、控制指标、结果证据和报告导出入口。",
        "若仅完成1 ms初始化和传播起始验证而未覆盖完整结构响应时程，系统将观察时间不足列为阻断条件，不得据此给出完整毁伤等级。若阈值缺失、单位不一致或材料模型不适用，则对象状态为无法评估并记录原因。",
    ]),
    ("六、实施例5：大语言模型受控调用现有工具", [
        "在可选实施方式中，用户将设施项目、爆炸目的、已有设计参数和期望输出提交给大语言模型。大语言模型将输入映射为受控场景中间表示候选，并列出装药当量、爆源位置、材料来源、边界范围或输出指标等关键缺失信息。用户补充并确认后，大语言模型生成工具调用计划。",
        "确定性控制器核对工具允许列表、输入模式、能力声明、项目修订、审批状态和调用预算。对于创建项目、保存草稿、生成预览和执行静态校验等低风险受控动作，控制器可以按策略执行；对于生成不可变K包、打开外部程序、启动求解或采用新的判据档案等动作，控制器要求显式用户批准。工具返回错误或警告时，大语言模型可以解释并提出候选修正，但不得直接修改工程文件。",
        "本实施例是对确定性建模内核的可选扩展。实施例1至实施例4的模型生成、校验和评估均不依赖大语言模型；关闭大语言模型后，用户仍可通过Web工作台或受控接口完成相同流程。",
    ]),
    ("七、实施状态和工程边界", [
        "当前确定性建模、商业建筑/住宅/地铁入口设施资源、TNT-ALE-FSI生成、分层预览、项目修订、验证门、K包生成、外部动作授权、运行证据登记和基于阈值档案的对象级评估已形成软件实现或验证链。大语言模型智能体属于可选扩展实施方式，其供应商适配、对话状态和受控工具编排可在后续实施，但不得作为当前三个求解实例已经完成的功能表述。",
        "上述1 ms求解仅证明初始化、空气传播起始和建筑响应到达，不构成足尺爆炸试验标定、完整时程毁伤预测、材料参数标定、网格独立性结论或工程设计审批。真实项目仍需工程人员对几何、材料、连接、装药、边界、网格、求解时长、结果收敛和阈值适用性进行复核。",
    ]),
]


FIGURES = [
    (FIGURE_DIR / "figure-01-overall-flow.png", "图1  面向城市关键基础设施爆炸毁伤的整体处理流程"),
    (FIGURE_DIR / "figure-02-system-architecture.png", "图2  系统模块结构"),
    (FIGURE_DIR / "figure-03-semantic-capability.png", "图3  受控解析、场景中间表示与能力匹配流程"),
    (FIGURE_DIR / "figure-04-deterministic-compiler.png", "图4  确定性物理模型编译与关键字文件生成流程"),
    (FIGURE_DIR / "figure-05-ale-fsi-physics.png", "图5  ALE空气域、TNT装药及结构FSI耦合关系"),
    (FIGURE_DIR / "figure-06-readiness-gates.png", "图6  多级校验、警告确认与生成就绪门禁"),
    (FIGURE_DIR / "figure-07-evidence-provenance.png", "图7  不可变项目修订与证据溯源关系"),
    (FIGURE_DIR / "figure-08-llm-controlled-tools.png", "图8  可选大语言模型受控工具调用流程"),
    (SCREENSHOT_DIR / "01-refined-commercial-overview.png", "图9  商业建筑精细爆炸模型工作台运行界面"),
    (SCREENSHOT_DIR / "07-refined-subway-components.png", "图10  地铁入口精细爆炸模型分层预览界面"),
    (IMPACT_SCREENSHOT, "图11  对象级智能毁伤评估界面"),
]


def set_run_font(run, name: str = "宋体", size: float = 10.5, bold: bool = False, color: str = "000000") -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def format_paragraph(paragraph, *, indent: bool = True, after: float = 3, line: float = 1.35) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = line
    if indent:
        paragraph.paragraph_format.first_line_indent = Pt(21)


def clear_cell(cell) -> None:
    for child in list(cell._tc):
        if child.tag != qn("w:tcPr"):
            cell._tc.remove(child)
    cell.add_paragraph()


def add_text(cell, text: str, *, bold: bool = False, heading: bool = False, formula: bool = False) -> None:
    paragraph = cell.add_paragraph()
    if heading:
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.space_before = Pt(5)
        paragraph.paragraph_format.space_after = Pt(3)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = paragraph.add_run(text)
        set_run_font(run, "黑体", 11, True)
        return
    if formula:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(4)
        paragraph.paragraph_format.line_spacing = 1.15
        run = paragraph.add_run(text)
        set_run_font(run, "Cambria Math", 10.5, False)
        return
    format_paragraph(paragraph, indent=not text[:2].rstrip(".、").isdigit())
    run = paragraph.add_run(text)
    set_run_font(run, "宋体", 10.5, bold)


def fill_structured(cell, sections) -> None:
    clear_cell(cell)
    first = cell.paragraphs[0]
    first._element.getparent().remove(first._element)
    for heading, paragraphs in sections:
        add_text(cell, heading, heading=True)
        for text in paragraphs:
            if text.startswith("FORMULA:"):
                add_text(cell, text.removeprefix("FORMULA:"), formula=True)
            else:
                add_text(cell, text)


def fill_plain(cell, paragraphs: list[str]) -> None:
    clear_cell(cell)
    first = cell.paragraphs[0]
    first._element.getparent().remove(first._element)
    for text in paragraphs:
        add_text(cell, text)


def set_cell_margins(cell, top: int = 90, start: int = 110, bottom: int = 90, end: int = 110) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for tag, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def remove_fixed_row_constraints(table) -> None:
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        for node in list(tr_pr):
            if node.tag in {qn("w:cantSplit"), qn("w:trHeight")}:
                tr_pr.remove(node)


def style_instruction_cells(table) -> None:
    for row in table.rows:
        cell = row.cells[0]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        set_cell_margins(cell, 100, 110, 100, 110)
        for paragraph in cell.paragraphs:
            paragraph.paragraph_format.space_after = Pt(2)
            paragraph.paragraph_format.line_spacing = 1.15
            for run in paragraph.runs:
                set_run_font(run, "宋体", 8.5, False, "555555")
        if cell.paragraphs and cell.paragraphs[0].runs:
            set_run_font(cell.paragraphs[0].runs[0], "黑体", 10, True, "222222")


def remove_content_after(element, document: Document) -> None:
    body = document._element.body
    current = element.getnext()
    while current is not None and current.tag != qn("w:sectPr"):
        nxt = current.getnext()
        body.remove(current)
        current = nxt


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("第 ")
    set_run_font(run, "宋体", 9)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)
    run = paragraph.add_run(" 页")
    set_run_font(run, "宋体", 9)


def configure_document(document: Document) -> None:
    document.core_properties.title = TITLE
    document.core_properties.subject = "发明（软件算法类）专利申请技术交底书"
    document.core_properties.author = ""
    document.core_properties.comments = "供专业专利代理机构评估及二次撰写"
    for section in document.sections:
        section.top_margin = Cm(1.55)
        section.bottom_margin = Cm(1.55)
        section.left_margin = Cm(1.55)
        section.right_margin = Cm(1.55)
        footer = section.footer
        footer.is_linked_to_previous = False
        footer.paragraphs[0].text = ""
        left = footer.paragraphs[0]
        left.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = left.add_run("技术交底书（供专利代理机构评估）")
        set_run_font(run, "宋体", 8.5, False, "666666")
        add_page_number(footer.add_paragraph())


def fill_header_table(table) -> None:
    table.cell(0, 1).text = TITLE
    table.cell(1, 1).text = "（待申请人填写）"
    table.cell(1, 3).text = "（待申请人填写）"
    table.cell(2, 1).text = "■ A、发明专利    □ B、实用新型    □ C、外观设计"
    for row in table.rows:
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell, 100, 120, 100, 120)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                for run in paragraph.runs:
                    set_run_font(run, "宋体", 10.5)
    for cell in (table.cell(0, 0), table.cell(1, 0), table.cell(1, 2), table.cell(2, 0)):
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                set_run_font(run, "黑体", 10, True)


def add_figures(document: Document) -> None:
    heading = document.add_paragraph()
    heading.paragraph_format.page_break_before = True
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run("附图")
    set_run_font(run, "黑体", 18, True)
    note = document.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.paragraph_format.space_after = Pt(10)
    run = note.add_run("以下附图用于说明技术关系和实施界面，不限定具体比例、颜色或软件布局。")
    set_run_font(run, "宋体", 10, False, "555555")
    for index, (path, caption) in enumerate(FIGURES):
        if not path.is_file():
            raise FileNotFoundError(path)
        paragraph = document.add_paragraph()
        if index > 0:
            paragraph.paragraph_format.page_break_before = True
        paragraph.paragraph_format.keep_with_next = True
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        run.add_picture(str(path), width=Cm(16.2))
        cap = document.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_before = Pt(4)
        cap.paragraph_format.space_after = Pt(0)
        run = cap.add_run(caption)
        set_run_font(run, "宋体", 10.5, False)


def build(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() != output_path.resolve():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
    document = Document(output_path)
    if len(document.tables) < 2:
        raise ValueError("converted template does not contain the expected two tables")
    configure_document(document)
    header_table, content_table = document.tables[:2]
    fill_header_table(header_table)
    remove_fixed_row_constraints(header_table)
    remove_fixed_row_constraints(content_table)
    style_instruction_cells(content_table)
    for row in content_table.rows:
        row.cells[-1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        set_cell_margins(row.cells[-1], 110, 130, 110, 130)

    fill_plain(content_table.cell(0, 1), [TITLE])
    fill_plain(content_table.cell(1, 1), TECHNICAL_FIELD)
    fill_structured(content_table.cell(2, 1), BACKGROUND)
    fill_structured(content_table.cell(3, 1), TECHNICAL_SOLUTION)
    fill_plain(content_table.cell(4, 1), BENEFITS)
    fill_plain(content_table.cell(5, 1), FIGURE_DESCRIPTIONS)
    fill_structured(content_table.cell(6, 1), EMBODIMENTS)

    remove_content_after(content_table._tbl, document)
    add_figures(document)
    document.save(output_path)
    print(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.input, args.output)


if __name__ == "__main__":
    main()
