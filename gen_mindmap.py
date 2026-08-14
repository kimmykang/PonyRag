"""Generate mind map for 欣生代产品Q&A"""
import json

doc = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://excalidraw.com",
    "elements": [],
    "appState": {
        "viewBackgroundColor": "#ffffff",
        "gridSize": 20,
        "gridModeEnabled": False
    },
    "files": {}
}

E = doc["elements"]

def rect(id_, x, y, w, h, sc, bc, text, sz=16):
    return {
        "type": "rectangle", "id": id_, "x": x, "y": y,
        "width": w, "height": h,
        "strokeColor": sc, "backgroundColor": bc,
        "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "angle": 0,
        "seed": hash(id_) % 100000, "version": 1, "versionNonce": hash(id_) % 99999,
        "isDeleted": False, "groupIds": [], "boundElements": None,
        "link": None, "locked": False, "roundness": {"type": 3},
        "text": text, "originalText": text,
        "fontSize": sz, "fontFamily": 3,
        "textAlign": "center", "verticalAlign": "middle",
        "lineHeight": 1.25
    }

def txt(id_, x, y, text, sz=16, sc=None, ta="center"):
    d = {
        "type": "text", "id": id_, "x": x, "y": y,
        "width": len(text) * sz * 0.6, "height": sz,
        "text": text, "originalText": text,
        "fontSize": sz, "fontFamily": 3,
        "textAlign": ta, "verticalAlign": "middle",
        "backgroundColor": "transparent", "fillStyle": "solid",
        "strokeWidth": 1, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "angle": 0,
        "seed": hash(id_) % 100000, "version": 1, "versionNonce": hash(id_) % 99999,
        "isDeleted": False, "groupIds": [], "boundElements": None,
        "link": None, "locked": False, "containerId": None,
        "lineHeight": 1.25
    }
    if sc:
        d["strokeColor"] = sc
    return d

def arrow(id_, x, y, tx, ty, sc="#1e3a5f"):
    dx, dy = tx - x, ty - y
    return {
        "type": "arrow", "id": id_, "x": x, "y": y,
        "width": abs(dx), "height": abs(dy),
        "strokeColor": sc, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "angle": 0,
        "seed": hash(id_) % 100000, "version": 1, "versionNonce": hash(id_) % 99999,
        "isDeleted": False, "groupIds": [], "boundElements": None,
        "link": None, "locked": False,
        "points": [[0, 0], [dx, dy]],
        "startBinding": None, "endBinding": None,
        "startArrowhead": None, "endArrowhead": "arrow"
    }

def line_el(id_, x, y, tx, ty, sc="#1e3a5f", sw=2):
    dx, dy = tx - x, ty - y
    return {
        "type": "line", "id": id_, "x": x, "y": y,
        "width": dx, "height": dy,
        "strokeColor": sc, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": sw, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "angle": 0,
        "seed": hash(id_) % 100000, "version": 1, "versionNonce": hash(id_) % 99999,
        "isDeleted": False, "groupIds": [], "boundElements": None,
        "link": None, "locked": False,
        "points": [[0, 0], [dx, dy]]
    }

def dot(id_, cx, cy, r=8, sc="#3b82f6"):
    return {
        "type": "ellipse", "id": id_,
        "x": cx - r, "y": cy - r,
        "width": r * 2, "height": r * 2,
        "strokeColor": sc, "backgroundColor": sc,
        "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
        "roughness": 0, "opacity": 100, "angle": 0,
        "seed": hash(id_) % 100000, "version": 1, "versionNonce": hash(id_) % 99999,
        "isDeleted": False, "groupIds": [], "boundElements": None,
        "link": None, "locked": False
    }


# ========== ROOT ==========
E.append(rect("root", 350, 10, 500, 50, "#1e40af", "#dbeafe", "2024 欣生代少儿高端医疗保险 Q&A", 22))
E.append(txt("root_sub", 600, 68, "MSH CHINA x 大地财险 | 经代渠道", 13, "#64748b"))
E.append(line_el("trunk", 600, 60, 600, 100, "#1e3a5f", 3))

# ========== SECTION HEADERS ==========
sx = [200, 600, 1000]
sec_colors = [("#1e40af", "#dbeafe"), ("#047857", "#a7f3d0"), ("#b45309", "#fef3c7")]
sec_labels = ["一、产品、保险福利及费率", "二、日常服务及医疗网络", "三、投保、核保及续保"]
for i in range(3):
    E.append(rect(f"sec{i}", sx[i] - 150, 100, 300, 38, sec_colors[i][0], sec_colors[i][1], sec_labels[i], 15))
    E.append(arrow(f"arrow_sec{i}", 600, 100, sx[i], 119, "#1e3a5f"))


# ========== SECTION 1 (LEFT) ==========
s1y = 150
labels1 = [
    ("卖点", [("唯一可单独投保的未成年人高医", 30), ("保障范围及机构覆盖超同类产品", 55), ("全网络直付不限儿科机构", 80), ("享MSH高端服务(专家推荐/绿色通道等)", 105), ("免费儿童体检+齿科涂氟福利", 130)], 0),
    ("ABC计划差异", [("A: 大陆|80万|免赔1万|不含昂贵", 30), ("B: 大陆|200万|免赔2千|可选昂贵", 55), ("C: 亚洲|800万|0免赔|含精神疾病", 80)], 160),
    ("除外责任", [("精神疾病(仅C含)","30"), ("先天/遗传性疾病","55"), ("基因检测/过敏原/微量元素检测","80"), ("矮小症/多动症/自闭症","105"), ("包皮环切/视力矫正","130")], 320),
    ("免赔额/等待期", [("A=1万 B=2000 C=0 (固定不可变)","30"), ("住院30天 门诊14天 (意外除外)","55")], 480),
    ("肿瘤治疗", [("涵盖: 内分泌疗法+免疫疗法+质子重离子","30")], 560),
    ("与精选区别", [("欣生代: 儿童单独投|大陆/亚洲","30"), ("精选: 全年龄段|全球|不可单独投","55"), ("满18岁免核保平移转精选大中华","80")], 620),
]

for label, details, y_offset in labels1:
    y = s1y + y_offset
    E.append(dot(f"s1dot_{y_offset}", sx[0], y + 15, 6, "#3b82f6"))
    E.append(line_el(f"s1line_{y_offset}", sx[0], y + 15, sx[0] - 110, y + 15, "#1e3a5f"))
    E.append(txt(f"s1lbl_{y_offset}", sx[0] - 230, y + 5, label, 14, "#374151", "left"))
    for dt, dy_off in details:
        dy = int(dy_off)
        E.append(line_el(f"s1d_{y_offset}_{dy}", sx[0] - 110, y + 15, sx[0] - 230, y + 15 + dy, "#64748b", 1))
        E.append(txt(f"s1dtxt_{y_offset}_{dy}", sx[0] - 380, y + dy, dt, 11, "#64748b", "left"))


# ========== SECTION 2 (CENTER) ==========
s2y = 150
labels2 = [
    ("医院范围", [("A/B/C均含公立+私立","30"), ("A不含昂贵; B/C可选含昂贵","55")], 0),
    ("昂贵医院", [("和睦家(部分除外)、协和国际部、百汇","30"), ("新世纪集团(自付30%)","55"), ("莱佛士/崔玉涛/港安/养和/新加坡伊丽莎白","80")], 120),
    ("直付服务", [("网络内: 住院+门诊直付","30"), ("非网络: 住院垫付","55"), ("先自付后微信/纸质理赔","80"), ("注意: 网络内未用直付=给付50%","105")], 240),
    ("优选网络", [("MSH精选儿科直付医院","30"), ("免费体检(年1次)+涂氟(年2次)","55"), ("不计入理赔/门诊次数","80")], 400),
    ("24h健康咨询", [("曜影执业医师视频/电话","30"), ("门诊+住院:10次/年 仅住院:5次/年","55"), ("可开3天OTC药MSH承担药费+配送","80")], 520),
    ("地域限制", [("非京津版: 京/津一般门诊最多赔2次","30")], 640),
]

for label, details, y_offset in labels2:
    y = s2y + y_offset
    E.append(dot(f"s2dot_{y_offset}", sx[1], y + 15, 6, "#3b82f6"))
    E.append(line_el(f"s2line_{y_offset}", sx[1], y + 15, sx[1] + 110, y + 15, "#1e3a5f"))
    E.append(txt(f"s2lbl_{y_offset}", sx[1] + 130, y + 5, label, 14, "#374151", "left"))
    for dt, dy_off in details:
        dy = int(dy_off)
        E.append(line_el(f"s2d_{y_offset}_{dy}", sx[1] + 110, y + 15, sx[1] + 230, y + 15 + dy, "#64748b", 1))
        E.append(txt(f"s2dtxt_{y_offset}_{dy}", sx[1] + 250, y + dy, dt, 11, "#64748b", "left"))


# ========== SECTION 3 (RIGHT) ==========
s3y = 150
labels3 = [
    ("投保条件", [("31天-17周岁投保|续保至17岁","30"), ("投保人须为法定监护人(父母)","55"), ("无国籍限制","80")], 0),
    ("核保要求", [("需健康告知","30"), ("6个月内: 生产出院小结+42天随访","55"), ("早产/试管: 同自然受孕标准","80"), ("仅电子版保单/直付卡","105")], 120),
    ("续保规则", [("降级: 不需重新核保","30"), ("升级: 需重新核保","55"), ("满18岁免核保平移转精选大中华","80")], 240),
    ("优客计划", [("0-3次且无住院: -10%(最多-20%)","30"), ("4-10次: 标准涨幅","55"), (">=11次: 标准+20%","80")], 360),
    ("线下流程", [("提交材料->核保(2-3日)->付款->收保单","30"), ("不建议: 效率低,仅电子版","55")], 480),
    ("生效规则", [("最早生效: 付款次日","30"), ("新生儿: 出生31天生效/28天可投","55"), ("网银转账非自动扣款","80")], 560),
]

for label, details, y_offset in labels3:
    y = s3y + y_offset
    E.append(dot(f"s3dot_{y_offset}", sx[2], y + 15, 6, "#3b82f6"))
    E.append(line_el(f"s3line_{y_offset}", sx[2], y + 15, sx[2] + 110, y + 15, "#1e3a5f"))
    E.append(txt(f"s3lbl_{y_offset}", sx[2] + 130, y + 5, label, 14, "#374151", "left"))
    for dt, dy_off in details:
        dy = int(dy_off)
        E.append(line_el(f"s3d_{y_offset}_{dy}", sx[2] + 110, y + 15, sx[2] + 230, y + 15 + dy, "#64748b", 1))
        E.append(txt(f"s3dtxt_{y_offset}_{dy}", sx[2] + 250, y + dy, dt, 11, "#64748b", "left"))


# ========== IMPORTANT NOTES ==========
E.append(txt("notes_title", 600, 740, "重要提示", 16, "#dc2626"))
notes_data = [
    ("事先授权: 特殊治疗需书面授权,否则按60%赔付", 200),
    ("48h紧急通知: 紧急治疗需48h内通知MSH审核", 600),
    ("公司抬头发票: 投保链接勾选+填公司全称税号", 1000),
]
for nt, nx in notes_data:
    E.append(rect(f"note_{nx}", nx - 190, 760, 380, 40, "#dc2626", "#fecaca", nt, 12))
    E.append(line_el(f"nline_{nx}", 600, 755, nx, 760, "#b91c1c", 1))

# FOOTER
E.append(txt("footer", 600, 830, "来源: MSH CHINA 2024欣生代产品Q&A(V4.1) | 版权 c 2024 MSH CHINA", 11, "#94a3b8"))


out_path = "d:/work/AI/insureai/欣生代产品Q&A思维导图.excalidraw"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)

print(f"Mind map created: {len(E)} elements -> {out_path}")
