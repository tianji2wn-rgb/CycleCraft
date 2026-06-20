import sys
import os
import json
from collections import Counter

# 确保 Windows 控制台中文输出不乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 将 src 目录加入 Python 搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from nicegui import ui
from cyclecraft import SequenceCalculator, ActionNode, DependencyType, calculate_uph

# 1. 初始化核心计算引擎
calculator = SequenceCalculator()

# 项目保存目录 (相对于 gui.py 所在目录)
PROJECTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

# 当前项目名称 (None 表示未命名)
current_project_name = None

# 2. 自动生成数字 ID 逻辑
def generate_next_id() -> str:
    """遍历当前节点，生成下一个唯一的递增数字 ID"""
    max_id = 0
    for nid in calculator.nodes:
        try:
            val = int(nid)
            if val > max_id:
                max_id = val
        except ValueError:
            pass
    return str(max_id + 1)

# 3. 预设模拟测试数据 ("气缸推料 -> 相机拍照 -> 机械手搬运")
def load_preset_data():
    preset_nodes = [
        ActionNode("1", "气缸推料", "气缸工位", 200.0),
        ActionNode("2", "相机拍照", "相机工位", 150.0),
        ActionNode("3", "吹气除尘", "相机工位", 100.0),
        ActionNode("4", "气缸复位", "气缸工位", 150.0),
        ActionNode("5", "机械手吸取", "机械手工位", 300.0),
        ActionNode("6", "机械手搬运", "机械手工位", 500.0),
    ]
    for node in preset_nodes:
        calculator.add_node(node)
        
    calculator.add_dependency("1", "2", DependencyType.FS, 0.0)
    calculator.add_dependency("2", "3", DependencyType.SS, 20.0)
    calculator.add_dependency("2", "4", DependencyType.FS, 0.0)
    calculator.add_dependency("2", "5", DependencyType.FS, 50.0)
    calculator.add_dependency("5", "6", DependencyType.FS, 0.0)

# 加载初始数据
load_preset_data()

# 用于将甘特图上柱状条的索引与动作 ID 进行映射的全局列表
row_action_ids = []

# 4. 项目序列化与反序列化逻辑
def serialize_project() -> str:
    """将动作列表和依赖关系序列化为 JSON 字符串"""
    data = {
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "station": node.station,
                "duration": node.duration
            }
            for node in calculator.nodes.values()
        ],
        "dependencies": [
            {
                "predecessor_id": dep.predecessor_id,
                "successor_id": dep.successor_id,
                "dep_type": dep.dep_type.value,
                "delay": dep.delay
            }
            for dep in calculator.dependencies
        ]
    }
    return json.dumps(data, indent=2, ensure_ascii=False)

def save_to_local(name: str):
    """将当前项目保存到本地 projects/ 目录"""
    global current_project_name
    json_content = serialize_project()
    filepath = os.path.join(PROJECTS_DIR, f"{name}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(json_content)
    current_project_name = name

def list_local_projects() -> list:
    """列出 projects/ 目录下所有 .json 文件名（不含扩展名）"""
    if not os.path.isdir(PROJECTS_DIR):
        return []
    return [
        os.path.splitext(f)[0]
        for f in os.listdir(PROJECTS_DIR)
        if f.endswith('.json')
    ]

def load_from_local(name: str):
    """从本地 projects/ 目录加载项目"""
    global current_project_name
    filepath = os.path.join(PROJECTS_DIR, f"{name}.json")
    with open(filepath, 'r', encoding='utf-8') as f:
        json_str = f.read()
    deserialize_project(json_str)
    current_project_name = name

def deserialize_project(json_str: str):
    """从 JSON 字符串反序列化恢复时序图，如果包含错误或循环依赖则回退"""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as je:
        raise ValueError(f"JSON 解析错误: {je}")

    if "nodes" not in data or "dependencies" not in data:
        raise ValueError("非法的项目配置文件格式：未包含完整的 nodes 或 dependencies 信息")
        
    # 事务性备份，用于在加载失败时执行回滚
    old_nodes = dict(calculator.nodes)
    old_dependencies = list(calculator.dependencies)
    
    calculator.nodes.clear()
    calculator.dependencies.clear()
    
    try:
        # 重构节点
        for n_data in data["nodes"]:
            node = ActionNode(
                id=str(n_data["id"]),
                name=n_data["name"],
                station=n_data["station"],
                duration=float(n_data["duration"])
            )
            calculator.add_node(node)
            
        # 重构依赖
        for d_data in data["dependencies"]:
            calculator.add_dependency(
                predecessor_id=str(d_data["predecessor_id"]),
                successor_id=str(d_data["successor_id"]),
                dep_type=DependencyType(d_data["dep_type"]),
                delay=float(d_data["delay"])
            )
        
        # 触发图引擎运算校验
        calculator.calculate()
        
    except Exception as e:
        # 数据加载产生冲突依赖，强行回退至修改前状态并抛出异常
        calculator.nodes.clear()
        calculator.nodes.update(old_nodes)
        for nid, n_obj in calculator.nodes.items():
            n_obj.id = nid
        calculator.dependencies = old_dependencies
        raise ValueError(f"项目加载失败，包含错误配置或循环依赖: {e}")

# 5. 构造表格的行数据结构
def get_row_data():
    rows = []
    for node in calculator.nodes.values():
        dep_list = []
        for dep in calculator.dependencies:
            if dep.successor_id == node.id:
                pred_node = calculator.nodes.get(dep.predecessor_id)
                pred_name = pred_node.name if pred_node else "未知"
                dep_list.append(f"{pred_name} (ID: {dep.predecessor_id}) [{dep.dep_type.value} + {dep.delay}ms]")
        dep_str = "、".join(dep_list) if dep_list else "无"
        rows.append({
            'id': node.id,
            'name': node.name,
            'station': node.station,
            'duration': node.duration,
            'predecessor': dep_str
        })
    return rows

# 6. 表格列定义
columns = [
    {'name': 'id', 'label': '唯一标识 (ID)', 'field': 'id', 'required': True, 'align': 'left'},
    {'name': 'name', 'label': '动作名称', 'field': 'name', 'align': 'left'},
    {'name': 'station', 'label': '所属工位', 'field': 'station', 'align': 'left'},
    {'name': 'duration', 'label': '标准耗时 (ms) [双击编辑]', 'field': 'duration', 'align': 'left'},
    {'name': 'predecessor', 'label': '前置关系 (依赖于)', 'field': 'predecessor', 'align': 'left'},
    {'name': 'actions', 'label': '操作', 'field': 'actions', 'align': 'right'}
]

# 7. UI 状态与 ECharts 图表刷新函数
def refresh_project_label():
    """更新导航栏中的项目名称显示"""
    if current_project_name:
        project_name_label.set_text(f"📁 {current_project_name}")
    else:
        project_name_label.set_text('未命名项目')

def refresh_ui():
    global row_action_ids
    try:
        results = calculator.calculate()
        ct = results["cycle_time"]
        uph = calculate_uph(ct, efficiency=0.85)
        path = results["critical_path"]
        
        # A. 更新看板指标
        ct_label.set_text(f"{ct:.1f} ms")
        uph_label.set_text(f"{uph:.1f} Pcs/h")
        
        # 格式化展示关键路径
        path_names = []
        for index, nid in enumerate(path):
            if nid in calculator.nodes:
                name = calculator.nodes[nid].name
                path_names.append(f"{index + 1}. {name} (ID: {nid})")
        path_label.set_text("\n ➔ \n".join(path_names) if path_names else "无")
        
        # 恢复看板卡片的正常工业蓝/绿/橙配色
        ct_card.classes(replace='bg-blue-50 border-blue-500')
        uph_card.classes(replace='bg-green-50 border-green-500')
        path_card.classes(replace='bg-orange-50 border-orange-500')

        # B. 更新 ECharts 时序甘特图 (游泳道/分组/高亮)
        node_times = results["node_times"]
        
        # 按照节点 ID 顺序排序（从上到下由小到大）
        sorted_nodes = sorted(
            calculator.nodes.values(),
            key=lambda n: int(n.id) if n.id.isdigit() else n.id
        )
        
        categories = []
        row_action_ids = []
        offset_data = []    # 系列 1 数据 (透明辅助柱)
        delay_data = []     # 系列 2 数据 (延迟时间辅助柱)
        duration_data = []  # 系列 3 数据 (实际耗时柱)
        
        for node in sorted_nodes:
            categories.append(f"{node.station}\n{node.name} (ID: {node.id})")
            row_action_ids.append(node.id)
            
            # 查找此节点前置关系中的延迟时间
            delay_time = 0.0
            for dep in calculator.dependencies:
                if dep.successor_id == node.id:
                    delay_time = dep.delay
                    break
                    
            start_time = node_times[node.id]["start"]
            
            # 开始时间减去延迟，就是透明辅助柱的宽度值
            offset_w = max(0.0, start_time - delay_time)
            offset_data.append(offset_w)
            
            # 实际延迟大小（若有）
            actual_delay = min(start_time, delay_time)
            if actual_delay > 0:
                delay_data.append(actual_delay)
            else:
                delay_data.append(None) # 使用 None 占位，ECharts 不会展示 0 ms 的标签
            
            # 分色：属于关键路径 (瓶颈工序) 的渲染为醒目的红褐色，普通渲染为浅蓝色
            is_critical = node.id in path
            color = '#ef4444' if is_critical else '#3b82f6'
            
            duration_data.append({
                'value': node.duration,
                'itemStyle': {
                    'color': color,
                    'borderRadius': 4
                }
            })
            
        # 计算瓶颈工序链（关键路径）的拐角圆角 S 形连接折线
        bottleneck_series_list = []
        node_row = {node.id: i for i, node in enumerate(sorted_nodes)}
        for i in range(len(path) - 1):
            pred_id = path[i]
            succ_id = path[i+1]
            if pred_id not in node_row or succ_id not in node_row:
                continue
            py = node_row[pred_id]
            sy = node_row[succ_id]
            px = node_times[pred_id]["end"]
            sx = node_times[succ_id]["start"]
            
            if py == sy:
                # 同一行直接水平直线连接
                path_data = [[px, py], [sx, sy]]
                smooth_val = 0
            else:
                # 跨行：横平竖直圆角 S 形弯曲折线
                mid_x = (px + sx) / 2
                path_data = [
                    [px, py],
                    [mid_x, py],
                    [mid_x, sy],
                    [sx, sy]
                ]
                # smooth 设为 0.18，让拐角圆滑过渡，形成精美的 S 形拐弯
                smooth_val = 0.18
                
            bottleneck_series_list.append({
                'name': '瓶颈工序链连线',
                'type': 'line',
                'data': path_data,
                'smooth': smooth_val,
                'symbol': ['none', 'arrow'],
                'symbolSize': 8,
                'lineStyle': {
                    'color': '#ef4444',
                    'width': 2,
                    'type': 'solid'
                },
                'label': {'show': False},
                'emphasis': {'disabled': True},
                'tooltip': {'show': False},
                'z': 10
            })

        chart.options['yAxis']['data'] = categories
        chart.options['series'] = [
            {
                'name': '开始时间',
                'type': 'bar',
                'stack': 'Total',
                'itemStyle': {
                    'borderColor': 'rgba(0,0,0,0)',
                    'color': 'rgba(0,0,0,0)'
                },
                'emphasis': {
                    'itemStyle': {
                        'borderColor': 'rgba(0,0,0,0)',
                        'color': 'rgba(0,0,0,0)'
                    }
                },
                'data': offset_data
            },
            {
                'name': '延迟时间',
                'type': 'bar',
                'stack': 'Total',
                'itemStyle': {
                    'color': 'rgba(244, 63, 94, 0.08)',
                    'borderColor': '#f43f5e',
                    'borderWidth': 1.5,
                    'borderType': 'dashed',
                    'borderRadius': 4
                },
                'label': {
                    'show': True,
                    'position': 'inside',
                    'formatter': '{c} ms',
                    'fontSize': 9,
                    'color': '#e11d48'
                },
                'data': delay_data
            },
            {
                'name': '动作耗时',
                'type': 'bar',
                'stack': 'Total',
                'label': {
                    'show': True,
                    'position': 'insideRight',
                    'formatter': '{c} ms'
                },
                'data': duration_data
            }
        ] + bottleneck_series_list
        chart.update()

        # C. 更新节点关系图 (水平泳道 + 横平竖直连线)
        path_set = set(path)

        # 拓扑深度（迭代计算直到稳定，正确处理 SS 依赖）
        node_ids = list(calculator.nodes.keys())
        depth = {nid: 0 for nid in node_ids}
        changed = True
        while changed:
            changed = False
            for dep in calculator.dependencies:
                pred_d = depth.get(dep.predecessor_id, 0)
                # SS: 同时开始，不增加深度；FS: 前置结束后开始，深度+1
                inc = 0 if dep.dep_type == DependencyType.SS else 1
                new_d = pred_d + inc
                if new_d > depth.get(dep.successor_id, 0):
                    depth[dep.successor_id] = new_d
                    changed = True

        # 为了解决同深度同工位节点重叠问题，我们需要动态计算每个工位的行高
        layers = {}
        for nid, d in depth.items():
            layers.setdefault(d, []).append(nid)
            
        stations = sorted({n.station for n in calculator.nodes.values()})
        
        # 统计每个工位在同一深度的最大并发节点数
        station_max_concurrent = {s: 1 for s in stations}
        for d, nids in layers.items():
            counts = Counter(calculator.nodes[nid].station for nid in nids)
            for s, c in counts.items():
                station_max_concurrent[s] = max(station_max_concurrent[s], c)
                
        # 动态计算每个工位的 Y 坐标范围与总高度
        station_y_min = {}
        station_y_max = {}
        current_y = 0
        node_h_spacing = 85  # 节点垂直间距，增高以提供更多垂直空隙
        
        for s in stations:
            station_y_min[s] = current_y
            # 泳道最小高度调大，确保即使没有并发也能有足够高度放置图标和节点
            req_h = max(110, station_max_concurrent[s] * node_h_spacing + 50)
            current_y += req_h
            station_y_max[s] = current_y
            
        max_d = max(depth.values()) if depth else 0
        x_gap = 210  # 增大横向间距，放置更宽的连线文本
        x_min = 0
        # 增加右边距，并配合起始偏移调大总宽度，容纳深度较大的节点
        x_max = max(1100, max_d * x_gap + 450)
        y_min = 0
        y_max = current_y

        # 动态计算图表容器宽高以适应节点数量，并更新图表样式（以支持 scroll_area 滚动）
        chart_w = max(1100, max_d * x_gap + 450)
        chart_h = max(380, len(stations) * 120 + 80)
        graph_chart.style(f'width: {chart_w}px; height: {chart_h}px;')

        grid_left = 40
        grid_right = 40
        grid_top = 20
        grid_bottom = 30
        
        # 计算像素与数据坐标转换比例，以便在数据坐标中实现精确的像素级偏移（如连接线刚好触及节点边缘）
        grid_w_px = chart_w - grid_left - grid_right
        grid_h_px = chart_h - grid_top - grid_bottom
        
        node_w_data = 110 * (x_max - x_min) / grid_w_px if grid_w_px > 0 else 0
        node_h_data = 42 * (y_max - y_min) / grid_h_px if grid_h_px > 0 else 0

        pos = {}
        for d, nids in layers.items():
            # 按工位分组，同工位同深度的节点垂直错开
            station_counts = Counter(calculator.nodes[nid].station for nid in nids)
            station_idx = {}
            for nid in nids:
                station = calculator.nodes[nid].station
                group_size = station_counts[station]
                idx = station_idx.get(station, 0)
                station_idx[station] = idx + 1
                
                # 起始坐标增加到 220，为左侧泳道名称 label 🏭 工位名称 留出绝对充足的像素空间
                x = 220 + d * x_gap
                y_center = (station_y_min[station] + station_y_max[station]) / 2
                
                # 垂直居中分布
                y = y_center + (idx - (group_size - 1) / 2) * node_h_spacing
                pos[nid] = (x, y)

        lane_colors = ['#f0f9ff', '#f0fdf4', '#fefce8', '#fdf2f8', '#f5f3ff', '#ecfdf5']
        mark_area_data = []
        for i, station in enumerate(stations):
            color = lane_colors[i % len(lane_colors)]
            mark_area_data.append([
                {
                    'yAxis': station_y_min[station],
                    'itemStyle': {'color': color, 'opacity': 0.6},
                    'label': {
                        'show': True,
                        'position': 'insideLeft',
                        'distance': 10,
                        'formatter': f'🏭 {station}',
                        'color': '#475569',
                        'fontSize': 13,
                        'fontWeight': 'bold'
                    }
                },
                {
                    'yAxis': station_y_max[station]
                }
            ])

        graphic_nodes = []
        graph_nodes = []
        for nid, node in calculator.nodes.items():
            is_critical = nid in path_set
            s = node_times[nid]['start']
            e = node_times[nid]['end']
            dx, dy = pos[nid]
            
            fill = '#ef4444' if is_critical else '#3b82f6'
            border = '#dc2626' if is_critical else '#2563eb'

            # 根据固定的图表分辨率精确计算节点中心的像素坐标 (X, Y)
            px = grid_left + (dx - x_min) / (x_max - x_min) * (chart_w - grid_left - grid_right)
            py = grid_top + (dy - y_min) / (y_max - y_min) * (chart_h - grid_top - grid_bottom)

            # 圆角矩形背景（通过 ECharts graphic 绘制像素级圆角，r: 8 保证是真正标准的圆角矩形）
            graphic_nodes.append({
                'type': 'rect',
                'left': px - 55,
                'top': py - 21,
                'shape': {'width': 110, 'height': 42, 'r': 8},
                'style': {
                    'fill': fill,
                    'stroke': border,
                    'lineWidth': 2,
                    'shadowBlur': 4,
                    'shadowColor': 'rgba(0,0,0,0.1)',
                    'shadowOffsetY': 2
                },
                'z': 10
            })
            # 动作名称文字标签 (graphic)
            graphic_nodes.append({
                'type': 'text',
                'x': px,
                'y': py - 8,
                'style': {
                    'text': node.name,
                    'textAlign': 'center',
                    'textVerticalAlign': 'middle',
                    'fill': '#fff',
                    'fontSize': 12,
                    'fontWeight': 'bold'
                },
                'z': 11
            })
            # 耗时数值标签 (graphic)
            graphic_nodes.append({
                'type': 'text',
                'x': px,
                'y': py + 10,
                'style': {
                    'text': f"{node.duration:.0f}ms",
                    'textAlign': 'center',
                    'textVerticalAlign': 'middle',
                    'fill': '#fff',
                    'fontSize': 11
                },
                'z': 11
            })

            # 透明的 scatter 节点，专门用来捕捉 Tooltip 浮层和 Click 事件
            graph_nodes.append({
                'name': f"{node.name}({nid})",
                'value': [dx, dy],
                'symbol': 'rect',
                'symbolSize': [110, 42],
                'itemStyle': {
                    'color': 'rgba(0,0,0,0)',
                    'borderColor': 'rgba(0,0,0,0)',
                    'borderWidth': 0
                },
                'label': {
                    'show': False
                },
                'tooltip': {
                    'formatter': f"<b>{node.name}</b> (ID: {nid})<br/>工位: {node.station}<br/>耗时: {node.duration:.1f} ms<br/>开始: {s:.1f} ms<br/>结束: {e:.1f} ms"
                }
            })

        edge_series = []
        for dep in calculator.dependencies:
            is_fs = dep.dep_type == DependencyType.FS
            label_text = f"{'FS' if is_fs else 'SS'}"
            if dep.delay > 0:
                label_text += f" +{dep.delay:.0f}ms"
                
            pred_node = calculator.nodes.get(dep.predecessor_id)
            succ_node = calculator.nodes.get(dep.successor_id)
            if not pred_node or not succ_node:
                continue
                
            sx, sy = pos[dep.predecessor_id]
            tx, ty = pos[dep.successor_id]
            
            # 精确计算连线的起点和终点，使之落在节点的外边缘
            if is_fs:
                # FS: 从前置右侧连向后置左侧
                line_sx = sx + node_w_data / 2
                line_tx = tx - node_w_data / 2
                mid_x = (line_sx + line_tx) / 2
                
                # 只有中间段的那个点才展示 label，防止在每个折线顶点都重复堆叠渲染 label
                path_data = [
                    [line_sx, sy],
                    [mid_x, sy],
                    {
                        'value': [mid_x, (sy + ty) / 2],
                        'label': {
                            'show': True,
                            'formatter': label_text,
                            'position': 'middle',
                            'fontSize': 9,
                            'color': '#64748b',
                            'backgroundColor': '#fff',
                            'padding': [1, 3]
                        }
                    },
                    [mid_x, ty],
                    [line_tx, ty]
                ]
            else:
                # SS: 从前置左侧连向后置左侧
                line_sx = sx - node_w_data / 2
                line_tx = tx - node_w_data / 2
                if abs(line_sx - line_tx) < 1:
                    path_data = [
                        [line_sx, sy],
                        {
                            'value': [line_sx, (sy + ty) / 2],
                            'label': {
                                'show': True,
                                'formatter': label_text,
                                'position': 'middle',
                                'fontSize': 9,
                                'color': '#64748b',
                                'backgroundColor': '#fff',
                                'padding': [1, 3]
                            }
                        },
                        [line_tx, ty]
                    ]
                else:
                    pad = 15
                    mid_x = min(line_sx, line_tx) - pad
                    path_data = [
                        [line_sx, sy],
                        [mid_x, sy],
                        {
                            'value': [mid_x, (sy + ty) / 2],
                            'label': {
                                'show': True,
                                'formatter': label_text,
                                'position': 'middle',
                                'fontSize': 9,
                                'color': '#64748b',
                                'backgroundColor': '#fff',
                                'padding': [1, 3]
                            }
                        },
                        [mid_x, ty],
                        [line_tx, ty]
                    ]
                    
            edge_series.append({
                'type': 'line',
                'data': path_data,
                'symbol': ['none', 'arrow'],
                'symbolSize': 8,
                'lineStyle': {
                    'color': '#3b82f6' if is_fs else '#22c55e',
                    'type': 'solid' if is_fs else 'dashed',
                    'width': 2
                },
                'label': {
                    'show': False
                },
                'emphasis': {'disabled': True},
                'tooltip': {'show': False},
                'z': 1
            })

        scatter_series = {
            'type': 'scatter',
            'data': graph_nodes,
            'z': 2,
            'silent': False,
            'markArea': {
                'silent': True,
                'data': mark_area_data
            }
        }

        # 移除了 ECharts 内置的 dataZoom，彻底禁用缩放行为。
        # 当元素过多时，依靠外层的 NiceGUI ui.scroll_area 滚动条进行原生的上下左右平移。
        if 'dataZoom' in graph_chart.options:
            del graph_chart.options['dataZoom']

        # 确保Y轴自上而下，同时清理遗留的graphic
        graph_chart.options['yAxis']['inverse'] = True
        graph_chart.options['xAxis']['min'] = x_min
        graph_chart.options['xAxis']['max'] = x_max
        graph_chart.options['yAxis']['min'] = y_min
        graph_chart.options['yAxis']['max'] = y_max
        graph_chart.options['graphic'] = graphic_nodes
        graph_chart.options['series'] = edge_series + [scatter_series]
        graph_chart.update()

    except ValueError as e:
        # 如果检测到循环依赖，更新看板为警示颜色与提示，并清空图表
        ct_label.set_text("配置冲突")
        uph_label.set_text("无法评估")
        path_label.set_text(f"检测到环路依赖:\n{str(e)}")
        
        ct_card.classes(replace='bg-red-50 border-red-500')
        uph_card.classes(replace='bg-red-50 border-red-500')
        path_card.classes(replace='bg-red-50 border-red-500')
        
        chart.options['yAxis']['data'] = []
        chart.options['series'][0]['data'] = []
        chart.options['series'][1]['data'] = []
        chart.update()

        graph_chart.options['series'] = []
        graph_chart.options['graphic'] = []
        graph_chart.update()
        
        ui.notify(f"图计算失败: {str(e)}", type='negative', position='top-right')

    # 更新动作表格
    table.rows = get_row_data()

    # 更新导航栏项目名称
    refresh_project_label()

# 8. 数据变动与本地存取回调函数
def handle_duration_update(node_id, new_duration):
    if node_id not in calculator.nodes:
        return
    try:
        old_duration = calculator.nodes[node_id].duration
        calculator.nodes[node_id].duration = float(new_duration)
        refresh_ui()
        ui.notify(f"动作 '{calculator.nodes[node_id].name}' 耗时已变更为 {new_duration} ms", type='positive')
    except Exception as e:
        # 异常回滚
        calculator.nodes[node_id].duration = old_duration
        refresh_ui()
        ui.notify(f"修改失败: {e}", type='negative')

def handle_delete_row(node_id):
    if node_id not in calculator.nodes:
        return
    try:
        old_node = calculator.nodes[node_id]
        # 级联删除相关的前置依赖
        old_deps = [dep for dep in calculator.dependencies if dep.predecessor_id == node_id or dep.successor_id == node_id]
        
        del calculator.nodes[node_id]
        calculator.dependencies = [dep for dep in calculator.dependencies if dep.predecessor_id != node_id and dep.successor_id != node_id]
        
        refresh_ui()
        ui.notify(f"已删除动作: {old_node.name} (ID: {node_id})", type='positive')
    except Exception as e:
        # 回退
        calculator.nodes[node_id] = old_node
        calculator.dependencies.extend(old_deps)
        refresh_ui()
        ui.notify(f"删除失败: {e}", type='negative')

def save_project():
    """保存项目到本地 projects/ 目录"""
    try:
        if current_project_name:
            save_to_local(current_project_name)
            ui.notify(f"项目已保存: {current_project_name}.json", type='positive')
        else:
            # 没有项目名，弹出命名对话框
            save_as_dialog.open()
    except Exception as e:
        ui.notify(f"项目保存失败: {e}", type='negative')

def new_project():
    """新建项目：弹出命名对话框"""
    new_project_name_input.value = ''
    new_project_dialog.open()

def clear_all():
    calculator.nodes.clear()
    calculator.dependencies.clear()
    refresh_ui()
    ui.notify("已清空所有动作节点和依赖关系", type='warning')

def reset_default():
    calculator.nodes.clear()
    calculator.dependencies.clear()
    load_preset_data()
    refresh_ui()
    ui.notify("已重置并加载默认时序测试数据", type='info')

# 9. 构建 NiceGUI 主界面
ui.query('body').style('background-color: #f8fafc;')

# 顶部导航栏
with ui.header().classes('bg-slate-800 text-white p-4 flex justify-between items-center shadow-lg'):
    with ui.row().classes('items-center gap-3'):
        ui.icon('timeline', size='md').classes('text-teal-400')
        with ui.column().classes('gap-0'):
            ui.label('CycleCraft').classes('text-xl font-bold tracking-wider')
            ui.label('自动化设备动作时序评估软件').classes('text-xs text-slate-400')
    with ui.row().classes('items-center gap-4'):
        project_name_label = ui.label('未命名项目').classes('text-sm text-teal-300 font-semibold')
        ui.label('单机运行评估工具 v1.0.0').classes('text-sm text-slate-300 font-light')

# 弹窗声明：新建项目命名对话框
with ui.dialog() as new_project_dialog, ui.card().classes('w-96 p-6 bg-white rounded-lg shadow-xl'):
    ui.label('📄 新建项目').classes('text-lg font-black text-slate-800 mb-4 border-b pb-2')
    new_project_name_input = ui.input('项目名称', placeholder='如: 气缸搬运线方案A').classes('w-full')

    def confirm_new_project():
        name = new_project_name_input.value.strip() if new_project_name_input.value else ""
        if not name:
            ui.notify("项目名称不能为空", type='warning')
            return
        # 检查是否重名
        existing = list_local_projects()
        if name in existing:
            ui.notify(f"项目 '{name}' 已存在，请使用其他名称", type='warning')
            return
        calculator.nodes.clear()
        calculator.dependencies.clear()
        save_to_local(name)
        refresh_ui()
        new_project_dialog.close()
        ui.notify(f"已新建项目: {name}", type='positive')

    with ui.row().classes('w-full justify-end gap-3 mt-4'):
        ui.button('取消', on_click=new_project_dialog.close).props('flat color=secondary')
        ui.button('确认创建', on_click=confirm_new_project).props('color=primary')

# 弹窗声明：另存为对话框（首次保存无项目名时使用）
with ui.dialog() as save_as_dialog, ui.card().classes('w-96 p-6 bg-white rounded-lg shadow-xl'):
    ui.label('💾 另存为').classes('text-lg font-black text-slate-800 mb-4 border-b pb-2')
    save_as_name_input = ui.input('项目名称', placeholder='如: 气缸搬运线方案A').classes('w-full')

    def confirm_save_as():
        name = save_as_name_input.value.strip() if save_as_name_input.value else ""
        if not name:
            ui.notify("项目名称不能为空", type='warning')
            return
        try:
            save_to_local(name)
            refresh_ui()
            save_as_dialog.close()
            ui.notify(f"项目已保存: {name}.json", type='positive')
        except Exception as e:
            ui.notify(f"保存失败: {e}", type='negative')

    with ui.row().classes('w-full justify-end gap-3 mt-4'):
        ui.button('取消', on_click=save_as_dialog.close).props('flat color=secondary')
        ui.button('保存', on_click=confirm_save_as).props('color=primary')

# 弹窗声明：打开项目（从本地 projects/ 目录选择）
with ui.dialog() as open_project_dialog, ui.card().classes('w-96 p-6 bg-white rounded-lg shadow-xl'):
    ui.label('📂 打开项目').classes('text-lg font-black text-slate-800 mb-4 border-b pb-2')
    open_project_select = ui.select(options=[], label='选择已有项目').classes('w-full')

    def refresh_project_list():
        projects = list_local_projects()
        open_project_select.options = projects
        if projects:
            open_project_select.value = projects[0]
        else:
            open_project_select.value = None

    def confirm_open_project():
        name = open_project_select.value
        if not name:
            ui.notify("请选择一个项目", type='warning')
            return
        try:
            load_from_local(name)
            refresh_ui()
            open_project_dialog.close()
            ui.notify(f"已加载项目: {name}", type='positive')
        except Exception as e:
            ui.notify(f"项目加载失败: {e}", type='negative')

    with ui.row().classes('w-full justify-end gap-3 mt-4'):
        ui.button('取消', on_click=open_project_dialog.close).props('flat color=secondary')
        ui.button('打开', on_click=confirm_open_project).props('color=primary')

# 主内容区域
with ui.row().classes('w-full p-6 justify-between items-stretch gap-6 no-wrap'):
    # 左半区：操作工具栏、时序甘特图、动作表格 (占宽 8/12)
    with ui.column().classes('w-8/12 gap-4'):
        # 操作工具栏
        with ui.card().classes('w-full p-4 flex-row items-center gap-3 bg-white border border-slate-100 shadow-sm'):
            ui.button('📄 新建项目', on_click=new_project).props('outline color=primary icon=note_add')
            ui.button('💾 保存项目', on_click=save_project).props('outline color=primary icon=save')
            ui.button('📂 打开项目', on_click=lambda: (refresh_project_list(), open_project_dialog.open())).props('outline color=primary icon=folder_open')
            ui.button('🔄 恢复默认', on_click=reset_default).props('flat color=secondary icon=refresh')

        # 时序甘特图容器
        with ui.card().classes('w-full p-4 bg-white border border-slate-100 shadow-sm'):
            ui.label('📊 动作时序甘特图 (点击下方柱状条可以直接修改属性，红色为瓶颈路径)').classes('text-base font-bold text-slate-700 mb-2')
            
            # ECharts 基础静态配置选项
            chart_options = {
                'tooltip': {
                    'trigger': 'axis',
                    'axisPointer': {'type': 'shadow'},
                    'formatter': '{b}<br/>基准开始: {c0} ms<br/>前置延时: {c1} ms<br/>动作耗时: {c2} ms'
                },
                'grid': {
                    'left': '3%',
                    'right': '4%',
                    'bottom': '3%',
                    'top': '12%',
                    'containLabel': True
                },
                'xAxis': {
                    'type': 'value',
                    'name': '时间 (ms)',
                    'position': 'top',
                    'axisLabel': {'formatter': '{value} ms'}
                },
                'yAxis': {
                    'type': 'category',
                    'data': [],
                    'inverse': True,
                    'axisLabel': {
                        'interval': 0,
                        'fontSize': 10
                    }
                },
                'series': [
                    {
                        'name': '开始时间',
                        'type': 'bar',
                        'stack': 'Total',
                        'itemStyle': {
                            'borderColor': 'rgba(0,0,0,0)',
                            'color': 'rgba(0,0,0,0)'
                        },
                        'emphasis': {
                            'itemStyle': {
                                'borderColor': 'rgba(0,0,0,0)',
                                'color': 'rgba(0,0,0,0)'
                            }
                        },
                        'data': []
                    },
                    {
                        'name': '延迟时间',
                        'type': 'bar',
                        'stack': 'Total',
                        'itemStyle': {
                            'color': 'rgba(244, 63, 94, 0.08)',  # 淡粉红色填充底纹
                            'borderColor': '#f43f5e',           # 玫瑰红边框
                            'borderWidth': 1.5,
                            'borderType': 'dashed',             # 虚线边框类型
                            'borderRadius': 4
                        },
                        'label': {
                            'show': True,
                            'position': 'inside',
                            'formatter': '{c} ms',
                            'fontSize': 9,
                            'color': '#e11d48'
                        },
                        'data': []
                    },
                    {
                        'name': '动作耗时',
                        'type': 'bar',
                        'stack': 'Total',
                        'label': {
                            'show': True,
                            'position': 'insideRight',
                            'formatter': '{c} ms'
                        },
                        'data': []
                    }
                ]
            }
            chart = ui.echart(options=chart_options).classes('w-full h-80')

            # 监听甘特图柱子点击事件，实现联动修改
            def handle_chart_click(e):
                args = e.args
                # 只有在点击动作柱体系列时触发
                if args.get('componentType') == 'series':
                    data_index = args.get('dataIndex')
                    if data_index is not None and data_index < len(row_action_ids):
                        action_id = row_action_ids[data_index]
                        open_edit_dialog(action_id)

            chart.on('click', handle_chart_click)

        # 节点关系图容器
        with ui.card().classes('w-full p-4 bg-white border border-slate-100 shadow-sm'):
            ui.label('🔗 节点依赖关系图 (蓝色实线=FS, 绿色虚线=SS, 红色=关键路径)').classes('text-base font-bold text-slate-700 mb-2')

            graph_options = {
                'grid': {
                    'left': 40, 'right': 40, 'top': 20, 'bottom': 30
                },
                'xAxis': {
                    'type': 'value', 'min': 0, 'max': 1000,
                    'axisLine': {'show': False}, 'axisTick': {'show': False},
                    'axisLabel': {'show': False}, 'splitLine': {'show': False}
                },
                'yAxis': {
                    'type': 'value', 'min': 0, 'max': 400,
                    'axisLine': {'show': False}, 'axisTick': {'show': False},
                    'axisLabel': {'show': False}, 'splitLine': {'show': False}
                },
                'tooltip': {
                    'trigger': 'item',
                    'formatter': '{b}'
                },
                'animationDuration': 200,
                'series': []
            }
            with ui.scroll_area().classes('w-full h-[450px]') as graph_scroll:
                graph_chart = ui.echart(options=graph_options).style('width: 100%; height: 400px;')

            def handle_graph_click(e):
                args = e.args
                if args.get('seriesType') == 'scatter':
                    name = args.get('name', '')
                    for nid, node in calculator.nodes.items():
                        if f"{node.name}({nid})" == name:
                            open_edit_dialog(nid)
                            break

            graph_chart.on('click', handle_graph_click)

        # 动作数据表格
        with ui.card().classes('w-full p-4 bg-white border border-slate-100 shadow-sm'):
            with ui.row().classes('w-full items-center justify-between mb-2'):
                ui.label('当前动作节点列表 (支持双击修改时间、点击右侧按钮编辑或删除)').classes('text-base font-bold text-slate-700')
                ui.button('➕ 添加动作', on_click=lambda: open_add_dialog()).props('color=primary icon=add dense')
            
            table = ui.table(
                columns=columns, 
                rows=get_row_data(), 
                row_key='id'
            ).classes('w-full')
            
            # 使用 Quasar 插槽：添加双击内联编辑耗时 (duration) 功能
            table.add_slot('body-cell-duration', '''
                <q-td :props="props" class="cursor-pointer font-medium text-blue-600">
                    {{ props.row.duration }} ms
                    <q-popup-edit v-model="props.row.duration" v-slot="scope" buttons label-set="确定" label-cancel="取消" @save="val => $parent.$emit('update_duration', {id: props.row.id, duration: val})">
                        <q-input type="number" v-model.number="scope.value" dense autofocus hint="双击并修改耗时 (ms)" />
                    </q-popup-edit>
                </q-td>
            ''')
            
            # 使用 Quasar 插槽：在表格右侧渲染操作编辑与删除按钮
            table.add_slot('body-cell-actions', '''
                <q-td :props="props" class="text-right">
                    <q-btn flat round dense color="primary" icon="edit" @click="$parent.$emit('edit_row', props.row.id)">
                        <q-tooltip>编辑该动作节点属性</q-tooltip>
                    </q-btn>
                    <q-btn flat round dense color="negative" icon="delete" @click="$parent.$emit('delete_row', props.row.id)">
                        <q-tooltip>删除该动作节点</q-tooltip>
                    </q-btn>
                </q-td>
            ''')
            
            # 监听表格中派发出来的 Vue 事件
            table.on('update_duration', lambda msg: handle_duration_update(msg.args['id'], msg.args['duration']))
            table.on('delete_row', lambda msg: handle_delete_row(msg.args))
            table.on('edit_row', lambda msg: open_edit_dialog(msg.args))

    # 右半区：三大指标看板 (占宽 4/12)
    with ui.column().classes('w-4/12 gap-4'):
        # 1. CT 看板
        with ui.card().classes('w-full p-5 bg-blue-50 border-l-8 border-blue-500 shadow-sm transition-all') as ct_card:
            ui.label('⏱️ 整机单周期耗时 (Cycle Time)').classes('text-sm text-slate-600 font-semibold')
            ct_label = ui.label('0.0 ms').classes('text-3xl font-black text-blue-800 tracking-tight mt-1')
            
        # 2. UPH 看板
        with ui.card().classes('w-full p-5 bg-green-50 border-l-8 border-green-500 shadow-sm transition-all') as uph_card:
            ui.label('⚡ 预测产能 (UPH @ 85% 效率)').classes('text-sm text-slate-600 font-semibold')
            uph_label = ui.label('0 Pcs/h').classes('text-3xl font-black text-green-800 tracking-tight mt-1')

        # 3. 关键路径看板
        with ui.card().classes('w-full p-5 bg-orange-50 border-l-8 border-orange-500 shadow-sm flex-1 transition-all') as path_card:
            ui.label('🔥 瓶颈工序链 (Critical Path)').classes('text-sm text-slate-600 font-semibold')
            path_label = ui.label('无').classes('text-base text-orange-850 font-medium whitespace-pre-wrap leading-relaxed mt-2')

# 工位选择中"新建工位"的特殊值
NEW_STATION = '__new__'

# 10. 添加新动作节点的弹出对话框 (无需手动输入动作 ID)
with ui.dialog() as add_dialog, ui.card().classes('w-[450px] p-6 bg-white rounded-lg shadow-xl'):
    ui.label('➕ 新建动作配置').classes('text-lg font-black text-slate-800 mb-4 border-b pb-2')

    with ui.column().classes('w-full gap-3'):
        node_name_input = ui.input('动作名称', placeholder='如: 气缸复位').classes('w-full').props('autocomplete=off')
        station_select = ui.select(options=[], label='所属工位/轴').classes('w-full')
        new_station_input = ui.input('新工位名称', placeholder='如: 气缸推料工位').classes('w-full').props('autocomplete=off')
        new_station_input.set_visibility(False)

        def on_station_change(e):
            new_station_input.set_visibility(e.args == NEW_STATION)
        station_select.on('update:model-value', on_station_change)

        duration_input = ui.number('标准动作耗时 (ms)', value=100.0, format='%.1f').classes('w-full').props('autocomplete=off')
        
        # 依赖勾选框
        dep_checkbox = ui.checkbox('配置前置动作依赖 (Dependency)')

        # 依赖选择面板（手动控制显示/隐藏，确保选项能正确刷新）
        dep_panel = ui.column().classes('w-full pl-4 border-l-4 border-slate-200 gap-3 mt-1 bg-slate-50 p-3 rounded')
        dep_panel.set_visibility(False)
        with dep_panel:
            pred_select = ui.select(options=[], label='选择前置动作').classes('w-full')
            dep_type_select = ui.select(
                options={'FS': 'Finish-to-Start (FS) - 前置结束，后置开始', 'SS': 'Start-to-Start (SS) - 前置开始，后置开始'},
                value='FS',
                label='依赖关系类型'
            ).classes('w-full')
            delay_input = ui.number('延时时间 delay (ms)', value=0.0, format='%.1f').classes('w-full')

        dep_checkbox.on('update:model-value', lambda e: dep_panel.set_visibility(e.args))
            
    with ui.row().classes('w-full justify-end gap-3 mt-6 border-t pt-3'):
        ui.button('取消', on_click=add_dialog.close).props('flat color=secondary')
        ui.button('确认保存', on_click=lambda: save_new_action()).props('color=primary')

# 11. 甘特图及表格修改动作节点属性的对话框 (全参数双向联动弹窗，动作 ID 设为只读)
with ui.dialog() as edit_dialog, ui.card().classes('w-[450px] p-6 bg-white rounded-lg shadow-xl'):
    ui.label('✏️ 修改动作配置').classes('text-lg font-black text-slate-800 mb-4 border-b pb-2')
    
    with ui.column().classes('w-full gap-3'):
        edit_id_label = ui.label('').classes('text-sm text-slate-500 font-bold mb-1 font-mono')
        edit_name_input = ui.input('动作名称', placeholder='如: 气缸复位').classes('w-full').props('autocomplete=off')
        edit_station_select = ui.select(options=[], label='所属工位/轴').classes('w-full')
        edit_new_station_input = ui.input('新工位名称', placeholder='如: 气缸推料工位').classes('w-full').props('autocomplete=off')
        edit_new_station_input.set_visibility(False)

        def on_edit_station_change(e):
            edit_new_station_input.set_visibility(e.args == NEW_STATION)
        edit_station_select.on('update:model-value', on_edit_station_change)

        edit_duration_input = ui.number('标准动作耗时 (ms)', format='%.1f').classes('w-full').props('autocomplete=off')
        
        # 依赖勾选
        edit_dep_checkbox = ui.checkbox('配置前置动作依赖 (Dependency)')

        # 依赖配置隐藏面板（手动控制显示/隐藏）
        edit_dep_panel = ui.column().classes('w-full pl-4 border-l-4 border-slate-200 gap-3 mt-1 bg-slate-50 p-3 rounded')
        edit_dep_panel.set_visibility(False)
        with edit_dep_panel:
            edit_pred_select = ui.select(options=[], label='选择前置动作').classes('w-full')
            edit_dep_type_select = ui.select(
                options={'FS': 'Finish-to-Start (FS) - 前置结束，后置开始', 'SS': 'Start-to-Start (SS) - 前置开始，后置开始'},
                value='FS',
                label='依赖关系类型'
            ).classes('w-full')
            edit_delay_input = ui.number('延时时间 delay (ms)', value=0.0, format='%.1f').classes('w-full')

        edit_dep_checkbox.on('update:model-value', lambda e: edit_dep_panel.set_visibility(e.args))
            
    with ui.row().classes('w-full justify-end gap-3 mt-6 border-t pt-3'):
        ui.button('取消', on_click=edit_dialog.close).props('flat color=secondary')
        ui.button('保存修改', on_click=lambda: save_edit()).props('color=primary')

current_edit_id = None

def save_edit():
    global current_edit_id
    if not current_edit_id or current_edit_id not in calculator.nodes:
        return
        
    nid = current_edit_id
    new_name = edit_name_input.value.strip() if edit_name_input.value else ""
    if edit_station_select.value == NEW_STATION:
        new_station = edit_new_station_input.value.strip() if edit_new_station_input.value else ""
    else:
        new_station = edit_station_select.value or ""
    new_duration = edit_duration_input.value
    
    # 验证输入有效性
    if not new_name:
        ui.notify("动作名称不能为空", type='warning')
        return
    if not new_station:
        ui.notify("工位名称不能为空", type='warning')
        return
    if new_duration is None or new_duration < 0:
        ui.notify("耗时必须为非负数", type='warning')
        return
        
    # 事务性备份以便在循环依赖等问题出现时回滚
    old_nodes_backup = dict(calculator.nodes)
    old_dependencies_backup = list(calculator.dependencies)
    
    try:
        node = calculator.nodes[nid]
                    
        # 更新节点的其他属性
        node.name = new_name
        node.station = new_station
        node.duration = float(new_duration)
        
        # 更新该动作的依赖项 (清除旧的前置依赖定义并添加新定义)
        calculator.dependencies = [dep for dep in calculator.dependencies if dep.successor_id != nid]
        
        if edit_dep_checkbox.value and edit_pred_select.value:
            pred_id = edit_pred_select.value
            dep_type = DependencyType(edit_dep_type_select.value)
            delay = float(edit_delay_input.value or 0.0)
            calculator.add_dependency(pred_id, nid, dep_type, delay)
            
        # 验证计算并更新视图
        refresh_ui()
        edit_dialog.close()
        ui.notify(f"修改成功: {new_name}", type='positive')
        
    except ValueError as e:
        # 回退恢复所有数据
        calculator.nodes.clear()
        calculator.nodes.update(old_nodes_backup)
        for n_id, n_obj in calculator.nodes.items():
            n_obj.id = n_id
        calculator.dependencies = old_dependencies_backup
        
        refresh_ui()
        ui.notify(f"修改动作失败，已撤销: {e}", type='negative')

def open_edit_dialog(action_id):
    global current_edit_id
    if action_id not in calculator.nodes:
        return
    node = calculator.nodes[action_id]
    current_edit_id = action_id
    
    # 填充基本信息，动作 ID 设为只读 Label 显示
    edit_id_label.set_text(f"动作 ID (系统只读): {node.id}")
    edit_name_input.value = node.name

    # 动态装载工位选项
    stations = sorted({n.station for n in calculator.nodes.values()})
    edit_station_options = {s: s for s in stations}
    edit_station_options[NEW_STATION] = '➕ 新建工位'
    edit_station_select.options = edit_station_options
    edit_station_select.update()
    edit_station_select.value = node.station
    edit_new_station_input.value = ''
    edit_new_station_input.set_visibility(False)

    edit_duration_input.value = node.duration
    
    # 获取并过滤可选的前置动作（排除自己，防环路）
    choices = {nid: f"{n.name} (ID: {nid})" for nid, n in calculator.nodes.items() if nid != node.id}
    edit_pred_select.options = choices
    edit_pred_select.update()

    # 查询是否存在依赖于其他动作的前置关系
    found_dep = None
    for dep in calculator.dependencies:
        if dep.successor_id == node.id:
            found_dep = dep
            break

    if found_dep:
        edit_dep_checkbox.value = True
        edit_dep_panel.set_visibility(True)
        edit_pred_select.value = found_dep.predecessor_id
        edit_dep_type_select.value = found_dep.dep_type.value
        edit_delay_input.value = found_dep.delay
    else:
        edit_dep_checkbox.value = False
        edit_dep_panel.set_visibility(False)
        if choices:
            edit_pred_select.value = list(choices.keys())[0]
        else:
            edit_pred_select.value = None
        edit_dep_type_select.value = 'FS'
        edit_delay_input.value = 0.0

    edit_dialog.open()

def open_add_dialog():
    node_name_input.value = ''
    duration_input.value = 100.0
    dep_checkbox.value = False
    dep_panel.set_visibility(False)

    # 动态装载工位选项
    stations = sorted({n.station for n in calculator.nodes.values()})
    station_options = {s: s for s in stations}
    station_options[NEW_STATION] = '➕ 新建工位'
    station_select.options = station_options
    station_select.update()
    station_select.value = stations[0] if stations else NEW_STATION
    new_station_input.value = ''
    new_station_input.set_visibility(False)

    # 动态装载可用的前置动作
    choices = {nid: f"{calculator.nodes[nid].name} (ID: {nid})" for nid in calculator.nodes}
    pred_select.options = choices
    pred_select.update()
    if choices:
        pred_select.value = list(choices.keys())[0]
    else:
        pred_select.value = None

    add_dialog.open()

def save_new_action():
    # 自动产生下一个全局唯一的数字 ID
    nid = generate_next_id()

    name = node_name_input.value.strip() if node_name_input.value else ""
    if station_select.value == NEW_STATION:
        station = new_station_input.value.strip() if new_station_input.value else ""
    else:
        station = station_select.value or ""
    duration = duration_input.value
    
    if not name:
        ui.notify("动作名称不能为空", type='warning')
        return
    if not station:
        ui.notify("工位名称不能为空", type='warning')
        return
    if duration is None or duration < 0:
        ui.notify("耗时必须为非负数", type='warning')
        return
        
    added_node = None
    added_dep = None
    try:
        node = ActionNode(id=nid, name=name, station=station, duration=float(duration))
        calculator.add_node(node)
        added_node = node
        
        if dep_checkbox.value and pred_select.value:
            pred_id = pred_select.value
            dep_type = DependencyType(dep_type_select.value)
            delay = float(delay_input.value or 0.0)
            
            calculator.add_dependency(pred_id, nid, dep_type, delay)
            added_dep = calculator.dependencies[-1]
            
        refresh_ui()
        add_dialog.close()
        ui.notify(f"添加节点成功: {name} (自动分配 ID: {nid})", type='positive')
        
    except ValueError as e:
        # 回退
        if added_node:
            del calculator.nodes[nid]
        if added_dep:
            calculator.dependencies.remove(added_dep)
        refresh_ui()
        ui.notify(f"动作保存失败，已撤销: {e}", type='negative')

# 12. 启动并执行首次计算渲染
refresh_ui()
ui.run(title='CycleCraft | 自动化设备动作时序图评估', host='127.0.0.1', port=8080, show=True)
