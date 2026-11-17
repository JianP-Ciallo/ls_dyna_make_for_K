"""Build the reviewed R12 reference catalog from local source files."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
import sqlite3
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.knowledge import ALLOWED_CASES, INDEXES, SUPPORT_TYPES
from lsprepost_mcp.schema import default_model_spec, generate_model_input_schema, parse_model_spec
from lsprepost_mcp.tools import TOOLS

STAGING = ROOT / "workspace/knowledge/lsdyna_20261107"
ARCHIVE = STAGING / "downloads/Intro_Examples_Input_Decks.curl.zip"
PAGE_DB = STAGING / "source_pages.sqlite"
OUTPUT = ROOT / "resources/knowledge/r12"
SUPPLEMENT_TOPICS = OUTPUT / "desktop_manual_topics.json"
CASE_RECIPES = OUTPUT / "official_case_recipes.json"
EXTERNAL_REFERENCES = OUTPUT / "external_reference_topics.json"
RECIPE_QUERY_ALIASES = {
    "boundary": ["边界条件", "边界设置", "约束怎么设"],
    "loading": ["载荷设置", "加载方式", "怎么加载", "初始条件"],
    "output": ["输出设置", "怎么设置输出", "结果输出"],
}
SITE = "https://lsdyna.ansys.com/"
INTRO = SITE + "introductory-tutorial-to-ls-dyna/"
LESSONS = (
    ("网格与 LS-PrePost 工具", "pMDSWH7NEipTkbw"),
    ("关键字与分析设置", "ZyxRLDPyXq6eyCA"),
    ("模型检查与 LS-Run", "xkKW9gzFky3wFqG"),
    ("结果分析", "PmiDpYHTbXF6xtc"),
)
ARCHIVE_SHA = "25751e9bee8ba346f9bd892e058eea35e2b9c9f3f2ca3a1baa69890c2e07a6b7"
MANUALS = {
    1: ("I", "9751d6add49a5cf38a8521cffed08dddea3cc5a6aadc93a776eeb5906248893e"),
    2: ("II", "a90d27d56282252f70bfa349006fb14e5b2539c9acbcc18a601a21d78fdbbe6f"),
}

# Only these members are admitted. Every deck is referenced in the original ZIP.
# Fields are case number, family, exact member suffix, title, query aliases,
# procedure, and the part of the workflow taught by the case.
CASES = (
    ("01", "shell_plate", "thin_shell_elform_2/ex_01_thin_shell_elform_2.k", "薄壳斜板法向受压",
     ["薄壳板受压", "薄壳板静力", "简支斜板"], "implicit",
     "简支薄壳斜板承受法向压力，参考壳截面、材料、压力面和输出配置。"),
    ("02", "thick_shell_plate", "thick_shell_elform_2/ex_02_thick_shell_elform_2.k", "厚壳斜板法向受压",
     ["厚壳斜板", "厚壳板静力"], "implicit",
     "厚壳斜板承受法向面压力，采用节点平移约束，输出厚壳单元历史及整模型状态。可与薄壳斜板对照。"),
    ("03", "solid_plate", "solid_elform_1/4x6x4_mesh/ex_03_solid_elform_1_4x6x4_mesh.k", "椭圆实体厚板受压粗网格",
     ["椭圆厚板粗网格", "椭圆板粗网格受压"], "implicit",
     "椭圆厚板采用实体单元，粗网格变体用于核对节点约束、法向压力面和应力输出。"),
    ("04", "solid_plate", "solid_elform_1/8x12x4_mesh/ex_04_solid_elform_1_8x12x4_mesh.k", "椭圆实体厚板受压细网格",
     ["椭圆厚板细网格", "椭圆板细网格受压"], "implicit",
     "椭圆厚板采用实体单元，细网格变体用于对照粗网格的压力面、监测位置和隐式求解设置。"),
    ("06", "beam_bar", "beam_elform_1/ex_06_beam_elform_1.k", "悬臂梁端部集中载荷",
     ["悬臂梁", "梁端加载", "悬臂梁端部力"], "implicit",
     "悬臂梁端部承受近轴向集中力，参考梁截面、固定节点、端点载荷和节点输出。"),
    ("07", "beam_bar", "beam_elform_1/ex_07_beam_elform_1.k", "Lee 梁架非线性屈曲",
     ["Lee梁架屈曲", "梁架载荷位移对照"], "implicit",
     "梁架两端铰支，受集中载荷。对照几何非线性求解、自动步进、节点力与位移曲线。"),
    ("08", "beam_bar", "beam_elform_1/ex_08_beam_elform_1.k", "两组交叉梁的面内模态",
     ["双十字梁面内模态", "铰支交叉梁振型"], "implicit",
     "交叉梁端点与内部节点采用不同自由度约束，用于对照接近的面内固有频率与振型。"),
    ("09", "shell_plate", "thin_shell_elform_16/ex_09_thin_shell_elform_16_ele_78.k", "简支环形薄板模态",
     ["环形薄板", "环板固有频率", "环形板粗网格"], "implicit",
     "薄壳环形板粗网格模态算例，用节点号区间建立节点集，并按节点集分别约束自由度。"),
    ("10", "shell_plate", "thin_shell_elform_16/ex_10_thin_shell_elform_16_ele_192.k", "简支环形薄板细网格模态",
     ["环形板细网格", "环板细网格固有频率"], "implicit",
     "薄壳环形板细网格模态算例，重选节点集后沿用粗网格的自由度和特征值设置，按振型对照频率。"),
    ("11", "beam_bar", "beam_elform_1/ex_11_beam_elform_1.k", "梁受恒力的隐式瞬态响应",
     ["梁受恒力", "梁瞬态响应", "梁节点集加载"], "implicit_transient",
     "梁承受由曲线逐渐升至恒值的节点集载荷，固定端与其余梁节点采用不同约束。对照支座反力、节点时程与动画输出。"),
    ("12", "solid_plate", "solid_elform_1/ex_12_solid_elform_1.k", "实体方板自由振动",
     ["实体方板模态", "实体方板固有频率"], "implicit",
     "简支方板采用实体网格，提取面外振动模态，适合对照支承和特征值设置。"),
    ("13", "thick_shell_plate", "thick_shell_elform_2/ex_13_thick_shell_elform_2.k", "厚壳方板自由振动",
     ["厚壳方板模态", "厚壳方板固有频率"], "implicit",
     "简支方板采用厚壳网格，提取面外振动模态，可与实体网格变体对照。"),
    ("14", "solid_plate", "solid_elform_1/ex_14_solid_elform_1.k", "实体方板瞬态受压",
     ["实体方板", "实体单元瞬态", "实体板阶跃压力"], "implicit_transient",
     "简支方板承受突加面压力，使用实体网格。参考时间曲线、监测节点和实体历史输出。"),
    ("15", "thick_shell_plate", "thick_shell_elform_2/ex_15_thick_shell_elform_2.k", "厚壳方板瞬态受压",
     ["方板瞬态受压", "厚壳方板", "板的瞬态振动", "厚壳板阶跃压力"], "implicit_transient",
     "简支方板承受突加面压力，使用厚壳网格。参考时间曲线、加载面和节点位移输出。"),
    ("16", "component_contact", "thin_shell_elform_13/ex_16_thin_shell_elform_13.k", "圆盘与柔性面接触",
     ["圆盘撞柔性面", "圆盘接触", "二维接触"], "implicit_transient",
     "圆盘撞击柔性表面，参考二维接触、部件关联、位移和接触反力输出。"),
    ("17", "spring_mass", "spring_elform_0/ex_17_spring_elform_0.k", "线性弹簧—质量自由振动",
     ["线性弹簧质量振动", "线性离散弹簧周期"], "explicit",
     "单个离散弹簧连接固定端和运动节点，使用常刚度和初始偏移。从节点时程测量振动周期。"),
    ("18", "spring_mass", "spring_elform_0/ex_18_spring_elform_0.k", "非线性弹簧—质量自由振动",
     ["非线性弹簧质量振动", "力位移曲线离散弹簧"], "explicit",
     "离散弹簧引用力—位移曲线，使用与线性算例相同的端点和集中质量。通过位移时程对照非线性振动。"),
    ("19", "shell_plate", "thin_shell_elform_16/29x76_mesh/ex_19_thin_shell_elform_16_29x76_mesh.k", "薄壁圆筒轴压线性屈曲",
     ["圆筒轴压屈曲", "薄壁筒屈曲模态"], "implicit",
     "小型薄壁圆筒的壳网格算例，比较上下边节点集的约束与加载，核对线性屈曲载荷倍数和振型。"),
    ("27", "explicit_impact", "solid_elform_-1_rpb/ex_27_solid_elform_-1_rigidwall.k", "铜杆撞刚壁显式算例",
     ["铜杆撞刚壁", "显式接触", "显式动力学"], "explicit",
     "铜杆撞击刚性壁面，作为显式求解、实体单元和刚壁约束的通用参考。"),
)

# Paired variants from the same official benchmark.
MESH_PAIRS = (("03", "04"), ("09", "10"))

# Geometry, element type, support, and excitation from the reviewed deck.
# The boundary recipe carries the keyword locations used for the support label.
CASE_APPLICABILITY = {
    "01": ("skew_plate", "shell", "simply_supported", "face_pressure"),
    "02": ("skew_plate", "thick_shell", "simply_supported", "face_pressure"),
    "03": ("elliptical_plate", "solid", "mixed_constraints", "face_pressure"),
    "04": ("elliptical_plate", "solid", "mixed_constraints", "face_pressure"),
    "06": ("cantilever_beam", "beam", "one_end_clamped", "point_force"),
    "07": ("plane_frame", "beam", "pinned_ends", "point_force"),
    "08": ("double_cross", "beam", "pinned_ends", "free_vibration"),
    "09": ("annular_plate", "shell", "simply_supported", "free_vibration"),
    "10": ("annular_plate", "shell", "simply_supported", "free_vibration"),
    "11": ("beam_with_lumped_mass", "beam", "mixed_constraints", "node_set_force"),
    "12": ("square_plate", "solid", "four_edges_simply_supported", "free_vibration"),
    "13": ("square_plate", "thick_shell", "four_edges_simply_supported", "free_vibration"),
    "14": ("square_plate", "solid", "four_edges_simply_supported", "face_pressure"),
    "15": ("square_plate", "thick_shell", "four_edges_simply_supported", "face_pressure"),
    "16": ("disk_and_flexible_surface", "shell_and_discrete", "contact_boundary", "body_acceleration"),
    "17": ("spring_mass", "discrete_and_mass", "one_node_fixed", "initial_spring_offset"),
    "18": ("spring_mass", "discrete_and_mass", "one_node_fixed", "initial_spring_offset"),
    "19": ("thin_walled_cylinder", "shell", "mixed_constraints", "node_set_force"),
    "27": ("bar_and_rigid_wall", "solid", "rigid_wall", "initial_velocity"),
}
CLAMPED_PLATE = OUTPUT / "fixtures/square_shell_four_edges_clamped.k"

# Locate the actual R12 card group, including its continuation pages.
# Columns are canonical card, aliases, volume, first/last PDF pages and summary.
CARDS = (
    ("*NODE", ["节点坐标", "网格节点"], 1, 2946, 2947, "定义节点 ID、坐标及全局平移与转动约束代码 TC、RC。"),
    ("*ELEMENT_SHELL", ["壳单元", "薄壳网格"], 1, 2323, 2331, "壳单元通过 PID 引用部件，并列出节点连接。"),
    ("*ELEMENT_SOLID", ["实体单元", "实体网格"], 1, 2343, 2350, "实体单元通过 PID 引用部件，节点数及续卡取决于选项。"),
    ("*ELEMENT_TSHELL", ["厚壳单元", "厚壳单元连接"], 1, 2361, 2365, "用 PID 连接部件，按厚壳选项填写节点与续卡。"),
    ("*ELEMENT_BEAM", ["梁单元连接", "梁网格方向"], 1, 2233, 2247, "核对梁单元的部件、端点、方向定义及适用续卡。"),
    ("*ELEMENT_MASS", ["节点附加质量", "集中质量单元"], 1, 2289, 2289, "按选项给节点或节点集定义集中质量，核对所引用对象及质量单位。"),
    ("*ELEMENT_DISCRETE", ["离散单元", "弹簧单元初始偏移"], 1, 2260, 2262, "以 PID 连接部件，核对两端节点、方向及 OFFSET 的初始位移或转角。"),
    ("*PART", ["部件卡", "部件关联"], 1, 2970, 2982, "部件将单元引用的 PID 连接到截面 SECID 与材料 MID。"),
    ("*SECTION_SHELL", ["薄壳截面", "壳单元厚度"], 1, 3103, 3123, "核对壳截面、单元公式、积分点及厚度续卡。"),
    ("*SECTION_SOLID", ["实体截面", "实体单元公式"], 1, 3124, 3142, "核对实体截面、单元公式及相应续卡。"),
    ("*SECTION_TSHELL", ["厚壳截面", "厚壳公式"], 1, 3147, 3149, "核对厚壳截面的单元公式及参数。"),
    ("*SECTION_BEAM", ["梁截面", "梁单元截面"], 1, 3064, 3084, "核对梁截面、公式及截面几何定义。"),
    ("*SECTION_DISCRETE", ["离散单元截面", "离散弹簧截面"], 1, 3089, 3091, "用 DRO 区分平移与转动离散单元，结合材料卡核对刚度、位移或转角及限制选项。"),
    ("*MAT_ELASTIC", ["*MAT_001", "弹性材料", "弹性模量"], 2, 190, 192, "MID 为材料 ID，RO 为密度，E 为弹性模量，PR 为泊松比。数值从对应材料来源取。"),
    ("*MAT_SPRING_ELASTIC", ["*MAT_S01", "线性弹簧材料", "弹簧常刚度"], 2, 1824, 1824, "K 为线性离散弹簧刚度。由截面类型判断是力/位移还是力矩/转角。"),
    ("*MAT_SPRING_NONLINEAR_ELASTIC", ["*MAT_S04", "非线性弹簧材料", "弹簧力位移曲线"], 2, 1827, 1827, "LCD 引用描述弹簧力与位移或力矩与转角关系的曲线或表，LCR 是可选的缩放曲线。"),
    ("*SET_NODE_LIST", ["*SET_NODE", "*SET_NODE_LIST_GENERATE", "*SET_NODE_LIST_TITLE", "节点集", "节点列表", "按节点号区间选点"], 1, 3197, 3203, "按 LIST 选项逐项列出节点 ID，或用 LIST_GENERATE 指定节点号区间。用 SID 标识集合，TITLE 选项可附名称。"),
    ("*BOUNDARY_SPC_SET", ["*BOUNDARY_SPC_NODE", "*BOUNDARY_SPC", "固定边", "节点约束", "锁定自由度"], 1, 725, 727, "以节点或节点集为约束对象，按坐标系锁定平移或转动自由度。核对 SID/NID、CID 和各 DOF 标志。"),
    ("*DEFINE_CURVE", ["载荷曲线", "压力时程", "时间曲线"], 1, 1925, 1928, "保存曲线 ID 和自变量、因变量序列，物理量及单位取决于引用它的卡。"),
    ("*LOAD_SEGMENT", ["面压力", "压力面", "表面压力"], 1, 2862, 2866, "核对受载面节点、压力曲线引用及方向定义。"),
    ("*LOAD_NODE_POINT", ["*LOAD_NODE_SET", "*LOAD_NODE", "节点力", "集中力"], 1, 2845, 2847, "核对受力节点或节点集、方向、曲线引用及比例系数。"),
    ("*CONTROL_IMPLICIT_GENERAL", ["隐式设置", "开启隐式"], 1, 1465, 1468, "检查隐式分析总开关及常用控制字段。"),
    ("*CONTROL_IMPLICIT_AUTO", ["隐式自动步进", "隐式自动调整步长"], 1, 1425, 1432, "核对隐式自动步进开关、迭代目标和步长范围，并与隐式初始步长设置联查。"),
    ("*CONTROL_IMPLICIT_BUCKLE", ["线性屈曲", "屈曲载荷倍数"], 1, 1433, 1434, "核对屈曲模态数和计算时刻。eigout 特征值是参考载荷的倍数，d3eigv 保存屈曲振型。"),
    ("*CONTROL_IMPLICIT_DYNAMICS", ["隐式动力学", "隐式瞬态"], 1, 1436, 1440, "检查隐式动力学配置与积分选项。"),
    ("*CONTROL_IMPLICIT_EIGENVALUE", ["模态提取", "特征值分析"], 1, 1441, 1448, "核对特征值数量、频率范围和提取设置。结果从 eigout 核对频率，从 d3eigv 查看振型。"),
    ("*CONTROL_IMPLICIT_SOLUTION", ["隐式迭代", "非线性收敛容差"], 1, 1497, 1508, "核对隐式平衡迭代的方法、迭代限制、刚度更新和收敛判据。"),
    ("*CONTROL_IMPLICIT_SOLVER", ["隐式线性求解器", "自动约束AUTOSPC"], 1, 1509, 1517, "核对隐式线性方程求解选项，以及 DRCM 和 AUTOSPC 对刚体运动与自由度的处理。"),
    ("*CONTROL_TERMINATION", ["终止时间", "结束时刻"], 1, 1668, 1669, "核对终止时间及其他终止判据。"),
    ("*CONTROL_TIMESTEP", ["时间步控制", "显式时间步"], 1, 1692, 1699, "核对时间步和质量缩放的选项，判断适用性需结合具体模型。"),
    ("*DATABASE_BINARY_D3PLOT", ["d3plot", "二进制结果", "云图输出", "变形回放", "整模型状态输出"], 1, 1745, 1752, "用 D3PLOT 按间隔保存模型网格的状态，用于回放变形和查看结果云图。按分析类型核对 DT 与相关选项。"),
    ("*DATABASE_BINARY_D3THDT", ["d3thdt", "二进制测点时程"], 1, 1745, 1752, "控制所选节点和单元的二进制时程输出，结合 DATABASE_HISTORY 选择对象并核对输出间隔。"),
    ("*DATABASE_EXTENT_BINARY", ["二进制结果变量", "云图缺少应变", "积分点输出"], 1, 1769, 1782, "控制二进制结果的内容和积分点信息。与指定输出文件及采样间隔的卡片配合使用。"),
    ("*DATABASE_HISTORY_NODE", ["历史节点", "位移测点"], 1, 1812, 1816, "在 HISTORY 的 NODE 选项中指定跟踪的节点，并核对所用输出方式。"),
    ("*DATABASE_NODOUT", ["nodout", "节点位移时程"], 1, 1727, 1740, "在 DATABASE_OPTION 中核对 NODOUT 和其输出间隔。"),
    ("*DATABASE_NODFOR", ["nodfor", "节点组力输出间隔"], 1, 1727, 1740, "请求节点组力数据库，设置采样间隔和输出方式。用 DATABASE_NODAL_FORCE_GROUP 选择节点组。"),
    ("*DATABASE_NODAL_FORCE_GROUP", ["节点组外力", "节点力输出分组"], 1, 1818, 1818, "以 NSID 选择节点组，以 CID 指定输出坐标系，并配合 DATABASE_NODFOR 设置输出间隔。"),
    ("*DATABASE_SPCFORC", ["spcforc", "支座反力", "约束反力输出"], 1, 1727, 1740, "请求单点约束的反力输出。核对输出间隔、存储方式及对应的约束节点。"),
    ("*CONTACT_2D_AUTOMATIC_NODE_TO_SURFACE", ["二维节点面接触", "二维接触卡"], 1, 1138, 1159, "在 CONTACT_2D 章节查对应选项及其引用的集合。"),
    ("*LOAD_BODY_Y", ["*LOAD_BODY", "体载荷", "加速度载荷"], 1, 2810, 2815, "核对基底加速度方向、曲线引用、比例系数和作用部件。"),
    ("*RIGIDWALL_PLANAR", ["刚性平面", "平面刚壁"], 1, 3046, 3055, "定义平面位置、法向、接触对象范围及可选参数。"),
    ("*INITIAL_VELOCITY_GENERATION", ["部件初始速度", "初速度卡"], 1, 2644, 2647, "核对 STYP 对应的引用类型、速度分量与坐标系。"),
    ("*MAT_RIGID", ["*MAT_020", "刚体材料", "刚体自由度"], 2, 269, 276, "核对刚体部件及可选的质心平移、转动约束。"),
    ("*DATABASE_HISTORY_SHELL", ["*DATABASE_HISTORY_SOLID", "*DATABASE_HISTORY_TSHELL", "*DATABASE_HISTORY_BEAM", "单元历史选择"], 1, 1812, 1816, "按 HISTORY 的 SHELL、SOLID、TSHELL 或 BEAM 选项指定对应类型的单元。"),
    ("*DATABASE_ELOUT", ["*DATABASE_RCFORC", "*DATABASE_RWFORC", "*DATABASE_GLSTAT", "*DATABASE_MATSUM", "单元与反力输出"], 1, 1727, 1740, "在 DATABASE_OPTION 中分别查单元结果、接触合力、刚壁力、全局统计和部件统计的输出设置。"),
)

TOOL_NOTES = {
    "generate_model": (["生成模型", "生成K文件"], "接收 spec 与 if_exists，写出模型 K、JSON、预览脚本和 checks.json。"),
    "import_keyword": (["导入K文件", "导入官方模型"], "在受支持的路径范围导入 K，创建项目并保存解析和静态检查结果。"),
    "validate_model": (["静态校验", "检查模型"], "按项目名重做静态检查并写 checks.json。"),
    "read_project": (["读取项目", "读取检查报告"], "读取模型和检查摘要。若检查缺失、无效或过期，会重写 checks.json。"),
    "model_summary": (["模型摘要", "节点单元统计"], "读取现有项目的模型结构和已有检查摘要。"),
    "validate_lsprepost_import": (["LS-PrePost导入验证", "检查关键字读入"], "调用 LS-PrePost 验证模型可读性，保存验证记录和预览文件。"),
    "export_preview_images": (["导出模型预览", "导出网格图"], "调用 LS-PrePost 生成指定视角的模型 PNG，输出用于输入模型预览。"),
}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def file_source(path: Path, locator: str, **metadata: object) -> dict:
    return {"path": relative(path), "sha256": digest(path.read_bytes()), "locator": locator, **metadata}


def source_for(function) -> dict:
    path = Path(inspect.getfile(function)).resolve()
    lines, first = inspect.getsourcelines(function)
    return file_source(path, f"{function.__name__}, lines {first}–{first + len(lines) - 1}")


def record(key: str, index: str, title: str, aliases: list[str], summary: str, source: dict, **fields: object) -> dict:
    return {"id": key, "index": index, "solver": "R12", "domain": "general_modeling",
            "case_families": sorted(ALLOWED_CASES), "title": title, "aliases": aliases,
            "summary": summary, "admitted": True, "reference_only": True, "source": source, **fields}


def keyword_blocks(text: str) -> list[dict]:
    lines = text.splitlines()
    starts = [(i, match.group().upper()) for i, line in enumerate(lines, 1)
              if (match := re.match(r"\*[A-Z0-9_]+", line.lstrip(), re.IGNORECASE))]
    return [{"keyword": name, "start_line": start,
             "end_line": starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines)}
            for i, (start, name) in enumerate(starts)]


def build_manual_records() -> list[dict]:
    sources = {}
    for volume, (roman, expected_sha) in MANUALS.items():
        path = STAGING / f"downloads/R12_Keyword_Vol_{roman}.curl.pdf"
        sources[volume] = file_source(path, "", url=SITE + "manuals-download/", source_release="R12")
        if sources[volume]["sha256"] != expected_sha:
            raise ValueError(f"unrecognized R12 manual: {path}")
    records = []
    with closing(sqlite3.connect(f"{PAGE_DB.as_uri()}?mode=ro", uri=True)) as db:
        for card, aliases, volume, start, end, summary in CARDS:
            source_id = f"web_r12_v{volume}"
            rows = db.execute("SELECT pdf_page,text FROM source_pages WHERE source_id=? AND pdf_page BETWEEN ? AND ? ORDER BY pdf_page",
                              (source_id, start, end)).fetchall()
            if [p for p, _ in rows] != list(range(start, end + 1)) or any(not text.strip() for _, text in rows):
                raise ValueError(f"incomplete source page range for {card}")
            source = {**sources[volume], "locator": f"Volume {MANUALS[volume][0]}, PDF {start}–{end}"}
            records.append(record(f"r12.{card[1:].lower()}", "I_model", card, aliases, summary, source,
                                  evidence_level="R12_manual_definition",
                                  manual={"source_id": source_id, "page_database": relative(PAGE_DB),
                                          "pages": [{"pdf_page": p, "sha256": digest(t.encode("utf-8"))} for p, t in rows]}))
    return records


def build_cases(manual: list[dict]) -> list[dict]:
    archive_source = file_source(ARCHIVE, "", source_release="introductory_examples_2013")
    if archive_source["sha256"] != ARCHIVE_SHA:
        raise ValueError("official example archive hash does not match the audited download")
    records = []
    if CASE_APPLICABILITY.keys() != {number for number, *_ in CASES}:
        raise ValueError("applicability metadata must cover every official case")
    with ZipFile(ARCHIVE) as archive:
        for number, family, filename, title, aliases, analysis, summary in CASES:
            member = f"example_{number}/{filename}"
            raw = archive.read(member)
            encoding = "ascii" if raw.isascii() else "cp1252"
            blocks = keyword_blocks(raw.decode(encoding))
            names = {block["keyword"] for block in blocks}
            if blocks[0]["keyword"] != "*KEYWORD" or blocks[-1]["keyword"] != "*END":
                raise ValueError(f"incomplete deck wrapper: {member}")
            if any(name.startswith("*INCLUDE") for name in names):
                raise ValueError(f"additional dependencies require review: {member}")
            if ("*CONTROL_IMPLICIT_GENERAL" in names) != analysis.startswith("implicit"):
                raise ValueError(f"analysis metadata does not match deck: {member}")
            ids = [r["id"] for r in manual if names.intersection([r["title"], *r["aliases"]])]
            source = {**archive_source, "locator": member, "url": SITE + f"example-{number}/",
                      "archive_url": SITE + "manuals-download/"}
            geometry, element, support, excitation = CASE_APPLICABILITY[number]
            if support not in SUPPORT_TYPES:
                raise ValueError(f"unsupported case support type: {support}")
            records.append(record(f"ansys.example_{number}", "I_case", title, aliases, summary, source,
                                  case_families=[family], analysis=analysis,
                                  applicability={"geometry": geometry, "element": element, "support": support,
                                                 "excitation": excitation, "evidence_id": f"guide.example_{number}.boundary"},
                                  evidence_level="official_original_static_inventory", r12_execution="unverified",
                                  unit_system="source_consistent_units_review_required",
                                  license_status="public_download_redistribution_unverified",
                                  deck={"member": member, "sha256": digest(raw), "encoding": encoding,
                                        "blocks": blocks, "external_includes": []},
                                  related_ids=[*ids, "run.workflow", "tool.import_keyword", "tool.validate_model"]))
    cases_by_id = {case["id"]: case for case in records}
    for coarse, fine in MESH_PAIRS:
        coarse_id, fine_id = f"ansys.example_{coarse}", f"ansys.example_{fine}"
        cases_by_id[coarse_id]["related_ids"].append(fine_id)
        cases_by_id[fine_id]["related_ids"].append(coarse_id)
    cases_by_id["ansys.example_17"]["related_ids"].append("ansys.example_18")
    cases_by_id["ansys.example_18"]["related_ids"].append("ansys.example_17")
    spec = default_model_spec(model_type="shell_plate")
    keyword, meta = build_keyword(parse_model_spec(spec))
    names = [block["keyword"] for block in keyword_blocks(keyword)]
    related = [r["id"] for r in manual if set(names).intersection([r["title"], *r["aliases"]])]
    records.append(record("project.shell_plate", "I_case", "项目单边固定薄板",
                          ["shell_plate", "单边固定薄板", "项目薄板模板"],
                          "项目默认薄板可生成壳网格、弹性材料和固定边。默认未施加载荷。",
                          source_for(default_model_spec), case_families=["shell_plate"],
                          applicability={"geometry": "rectangular_plate", "element": "shell",
                                         "support": "one_edge_clamped", "excitation": "none"},
                          supporting_sources=[source_for(build_keyword)],
                          evidence_level="generated_in_memory", r12_execution="unverified",
                          spec=spec, keyword_names=names,
                          mesh_counts={key: meta[key] for key in ("node_count", "element_count", "load_count")},
                          related_ids=[*related, "run.workflow", "tool.generate_model", "tool.validate_model"]))
    raw = CLAMPED_PLATE.read_bytes()
    blocks = keyword_blocks(raw.decode("ascii"))
    names = {block["keyword"] for block in blocks}
    linked = [r["id"] for r in manual if names.intersection([r["title"], *r["aliases"]])]
    records.append(record("project.square_shell_four_edges_clamped", "I_case", "四边固支薄壳方板模态",
                          ["四边固支薄壳方板", "四周夹紧薄板模态", "four-edge clamped square shell plate"],
                          "项目自建静态核对样例。方板用薄壳单元离散，周边节点约束六个自由度，提取无外载固有模态。",
                          file_source(CLAMPED_PLATE, CLAMPED_PLATE.name, source_release="project_fixture"),
                          case_families=["shell_plate"], analysis="implicit",
                          applicability={"geometry": "square_plate", "element": "shell", "support": "four_edges_clamped",
                                         "excitation": "free_vibration", "evidence_id": "guide.project.square_shell_four_edges_clamped.boundary"},
                          evidence_level="project_fixture_static_inventory", r12_execution="unverified",
                          deck={"member": CLAMPED_PLATE.name, "sha256": digest(raw), "encoding": "ascii",
                                "blocks": blocks, "external_includes": [], "standalone": True},
                          related_ids=[*linked, "run.workflow", "tool.import_keyword", "tool.validate_model"]))
    return records


def build_case_recipes(cases: list[dict], manual: list[dict]) -> list[dict]:
    curated = json.loads(CASE_RECIPES.read_text(encoding="utf-8"))
    originals = {case["id"]: case for case in cases if case.get("deck")}
    if originals.keys() != curated.keys():
        raise ValueError("recipe case IDs do not match the deck inventory")
    keyword_references = {}
    for item in manual:
        for label in [item["title"], *item["aliases"]]:
            if label.startswith("*"):
                keyword_references[label] = item["id"]

    records = []
    for case_id, topics in curated.items():
        case = originals[case_id]
        if sorted(t["topic"] for t in topics) != sorted(RECIPE_QUERY_ALIASES):
            raise ValueError(f"expected boundary, loading and output recipes for {case_id}")
        for topic in topics:
            category = topic["topic"]
            if not all(topic.get(key) for key in ("steps", "adaptation", "checks", "evidence")):
                raise ValueError(f"incomplete {category} recipe for {case_id}")
            blocks = []
            manual_ids = []
            for selector in topic["evidence"]:
                if isinstance(selector, dict):
                    keyword, occurrence = selector["keyword"], None
                else:
                    keyword, occurrence = (selector, None) if isinstance(selector, str) else selector
                matches = [b for b in case["deck"]["blocks"] if b["keyword"] == keyword]
                if not matches or (occurrence is not None and not 1 <= occurrence <= len(matches)):
                    raise ValueError(f"missing evidence {selector!r} in {case_id}")
                if isinstance(selector, dict):
                    start, end = selector["lines"]
                    if not any(b["start_line"] <= start <= end <= b["end_line"] for b in matches):
                        raise ValueError(f"excerpt outside {keyword} in {case_id}")
                    blocks.append({"keyword": keyword, "start_line": start, "end_line": end})
                else:
                    blocks.extend(matches if occurrence is None else [matches[occurrence - 1]])
                manual_ids.append(keyword_references[keyword])
            spans = ", ".join(f"{b['start_line']}–{b['end_line']}" for b in blocks)
            key = f"guide.{case_id.removeprefix('ansys.')}.{category}"
            source = {**case["source"], "locator": f"{case['deck']['member']}, lines {spans}"}
            records.append(record(key, "I_model", topic["title"], topic["aliases"], topic["summary"], source,
                                  case_families=case["case_families"], analysis=case["analysis"],
                                  evidence_level=("project_fixture_annotated_static" if case["deck"].get("standalone")
                                                  else "official_deck_annotated_static"),
                                  r12_execution=case["r12_execution"],
                                  related_ids=[case_id, *dict.fromkeys(manual_ids)],
                                  recipe={"case_id": case_id, "topic": category, "source_blocks": blocks,
                                          "steps": topic["steps"], "adaptation": topic["adaptation"],
                                          "checks": topic["checks"], "query_aliases": RECIPE_QUERY_ALIASES[category]}))
            case["related_ids"].append(key)
    return records


def build_tools() -> list[dict]:
    tools_source = file_source(ROOT / "lsprepost_mcp/tools.py", "TOOLS registration")
    records = []
    for name, (aliases, summary) in TOOL_NOTES.items():
        description, schema, function = TOOLS[name]
        supporting = [tools_source]
        if name == "generate_model":
            from lsprepost_mcp.project_store import write_model_project

            supporting.extend([source_for(generate_model_input_schema), source_for(write_model_project)])
        records.append(record(f"tool.{name}", "I_tool", name, aliases, summary, source_for(function),
                              supporting_sources=supporting, input_schema=schema,
                              registered_description=description, evidence_level="source_contract"))
    return records


def build_run() -> list[dict]:
    from lsprepost_mcp.lsdyna_runner import execute_lsdyna_run
    from lsprepost_mcp.solver_results import parse_d3hsp, parse_nodout
    from lsprepost_mcp.tool_project import tool_validate_model

    workflow = record("run.workflow", "I_run", "建模检查求解后处理流程",
                      ["建模流程", "入门教程", "官方四段教程"],
                      "依次准备网格与关键字、检查模型、按项目流程执行求解、读取结果。官方视频展示相同顺序。",
                      {**source_for(tool_validate_model), "tutorial_url": INTRO},
                      evidence_level="documented_workflow",
                      steps=["网格与几何", "关键字与材料设置", "静态与读入检查", "求解", "结果核对"],
                      tutorial_versions={"LS-PrePost": "4.9", "LS-Run": "1.0"},
                      tutorial_lessons=[{"title": title, "asset_url": f"https://files.dynamore.se/index.php/s/{token}",
                                         "local_asset_status": "remote_timeout"} for title, token in LESSONS],
                      related_ids=["tool.validate_model", "tool.validate_lsprepost_import", "run.solver", "run.results"])
    solver = record("run.solver", "I_run", "求解输入快照与日志",
                    ["求解流程", "求解日志", "求解输入快照"],
                    "现有求解服务按项目构建输入快照，记录求解器身份、资源、运行状态与日志。",
                    source_for(execute_lsdyna_run), evidence_level="source_contract",
                    related_ids=["tool.validate_model", "run.results"])
    results = record("run.results", "I_run", "求解终止与节点结果检查",
                     ["检查d3hsp", "求解终止", "读取位移时程", "结果检查"],
                     "先从日志核对求解状态，再用本次运行的输出检查目标位移。节点输出取决于模型请求的数据库卡。",
                     source_for(parse_d3hsp), supporting_sources=[source_for(parse_nodout)],
                     evidence_level="source_contract",
                     related_ids=["r12.database_binary_d3plot", "r12.database_history_node", "r12.database_nodout"])
    return [workflow, solver, results]


def build_supplements() -> list[dict]:
    topics_by_source = json.loads(SUPPLEMENT_TOPICS.read_text(encoding="utf-8"))
    records = []
    with closing(sqlite3.connect(f"{PAGE_DB.as_uri()}?mode=ro", uri=True)) as db:
        documents = db.execute(
            "SELECT filename, source_id, solver_release, sha256 FROM source_documents "
            "WHERE source_id GLOB 'local_*'"
        ).fetchall()
        if {filename for filename, *_ in documents} != topics_by_source.keys():
            raise ValueError("supplement topic sources differ from the audited user documents")
        for filename, source_id, release, expected in sorted(documents):
            path = STAGING / "manuals" / filename
            original = path.read_bytes()
            if digest(original) != expected:
                raise ValueError(f"audited source changed: {path}")
            if not topics_by_source[filename]:
                raise ValueError(f"user document has no topic records: {filename}")
            solver_match = re.match(r"R\d+", release)
            solver = solver_match.group() if solver_match else None
            is_pdf = path.suffix.lower() == ".pdf"
            lines = original.decode("utf-8").splitlines() if not is_pdf else None
            for topic in topics_by_source[filename]:
                start, end = topic["span"]
                source = {"path": relative(path), "filename": filename, "source_id": source_id,
                          "sha256": expected, "source_release": release,
                          "locator": f"PDF {start}–{end}" if is_pdf else f"TXT lines {start}–{end}"}
                if is_pdf:
                    rows = db.execute("SELECT pdf_page,text FROM source_pages WHERE source_id=? "
                                      "AND pdf_page BETWEEN ? AND ? ORDER BY pdf_page", (source_id, start, end)).fetchall()
                    if [p for p, _ in rows] != list(range(start, end + 1)) or any(not content.strip() for _, content in rows):
                        raise ValueError(f"missing excerpt in {filename}: {start}–{end}")
                    reference = {"manual": {"source_id": source_id, "page_database": relative(PAGE_DB),
                                            "pages": [{"pdf_page": page, "sha256": digest(content.encode("utf-8"))}
                                                      for page, content in rows]}}
                else:
                    if not 1 <= start <= end <= len(lines):
                        raise ValueError(f"invalid text range in {filename}: {start}–{end}")
                    reference = {"text_excerpt": {"encoding": "utf-8", "start_line": start, "end_line": end}}
                supplemental = {k: v for k, v in topic.items() if k not in {"id", "index", "title", "aliases", "summary", "span"}}
                records.append(record(topic["id"], topic["index"], topic["title"], topic["aliases"], topic["summary"],
                                      source, **supplemental, **reference, solver=solver, collection="supplement",
                                      runtime_admitted=False, evidence_level="historical_or_conceptual_reference"))
    return records


def build_external_references() -> list[dict]:
    """Publish only curated excerpts from fixed, locally verified upstream files."""
    manifest = json.loads(EXTERNAL_REFERENCES.read_text(encoding="utf-8"))
    source_dir = STAGING / "downloads/open_decks"

    def checked_source(spec: dict) -> tuple[dict, bytes]:
        path = source_dir / spec["file"]
        raw = path.read_bytes()
        if digest(raw) != spec["sha256"]:
            raise ValueError(f"external source changed: {path}")
        return {"path": relative(path), "sha256": spec["sha256"], "url": spec["url"]}, raw

    records = []
    for item in manifest:
        source, raw = checked_source(item)
        support = []
        for spec in item.get("supporting_files", []):
            supporting_source, _ = checked_source(spec)
            support.append({**supporting_source, "locator": spec["locator"]})
        if "license_file" in item:
            license_source, _ = checked_source(item["license_file"])
            support.append({**license_source, "locator": "upstream license"})
        source["source_release"] = item["release"]
        source["license_status"] = item["license"]
        encoding = item.get("encoding", "utf-8")
        lines = raw.decode(encoding).splitlines() if any("span" in topic for topic in item["topics"]) else []
        for topic in item["topics"]:
            location = topic["locator"]
            extra = {"steps": topic["steps"], "checks": topic["checks"],
                     "related_ids": topic.get("related_ids", [])}
            if "span" in topic:
                start, end = topic["span"]
                if not 1 <= start <= end <= len(lines) or topic["anchor"] not in lines[start - 1]:
                    raise ValueError(f"external excerpt does not match source: {topic['id']}")
                extra["text_excerpt"] = {"encoding": encoding, "start_line": start, "end_line": end}
                location += f", lines {start}–{end}"
            records.append(record(topic["id"], item["index"], topic["title"], topic["aliases"], topic["summary"],
                                  {**source, "locator": location}, supporting_sources=support,
                                  collection="supplement", solver=None, runtime_admitted=False,
                                  evidence_level=item["evidence_level"], **extra))
    return records


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> None:
    manual = build_manual_records()
    cases = build_cases(manual)
    for entry in manual:
        families = {family for case in cases if entry["id"] in case["related_ids"] for family in case["case_families"]}
        if not families:
            raise ValueError(f"manual entry lacks a supported case: {entry['id']}")
        entry["case_families"] = sorted(families)
    indexes = {"I_case": cases, "I_model": [*manual, *build_case_recipes(cases, manual)],
               "I_run": build_run(), "I_tool": build_tools()}
    for entry in [*build_supplements(), *build_external_references()]:
        indexes[entry["index"]].append(entry)
    files = {f"{index}.json": json_bytes({"records": indexes[index]}) for index in INDEXES}
    fingerprint = digest(b"".join(files.values()))
    catalog = json_bytes({"schema_version": 1, "path_base": "../../..", "snapshot_sha256": fingerprint,
                          "index_files": list(files)})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, data in {**files, "catalog.json": catalog}.items():
        target = OUTPUT / name
        staged = target.with_suffix(".tmp")
        staged.write_bytes(data)
        staged.replace(target)
    print(json.dumps({index: len(records) for index, records in indexes.items()}))


if __name__ == "__main__":
    main()
