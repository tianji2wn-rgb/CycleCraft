from typing import Dict, List, Tuple, Set
import networkx as nx
from .models import ActionNode, Dependency, DependencyType

class SequenceCalculator:
    """
    动作时序及周期计算引擎。
    使用事件级有向无环图 (Event-Level DAG) 进行绝对时间调度与关键路径分析。
    """
    def __init__(self):
        self.nodes: Dict[str, ActionNode] = {}
        self.dependencies: List[Dependency] = []

    def add_node(self, node: ActionNode) -> None:
        """
        添加动作节点。
        """
        if node.id in self.nodes:
            raise ValueError(f"动作节点 ID 重复: {node.id}")
        self.nodes[node.id] = node

    def add_dependency(self, predecessor_id: str, successor_id: str, dep_type: DependencyType, delay: float = 0.0) -> None:
        """
        添加动作节点之间的依赖关系。
        """
        if predecessor_id not in self.nodes:
            raise ValueError(f"前置节点不存在: {predecessor_id}")
        if successor_id not in self.nodes:
            raise ValueError(f"后置节点不存在: {successor_id}")
        
        dep = Dependency(
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            dep_type=dep_type,
            delay=delay
        )
        self.dependencies.append(dep)

    def calculate(self) -> Dict:
        """
        计算每个动作的起止时间、整机周期 (CT) 以及关键路径。
        
        返回字典:
        {
            "node_times": { node_id: {"start": float, "end": float} },
            "cycle_time": float,
            "critical_path": List[str]  # 关键路径上的动作节点 ID 列表
        }
        """
        if not self.nodes:
            return {
                "node_times": {},
                "cycle_time": 0.0,
                "critical_path": []
            }

        # 1. 构造事件级有向图
        G = nx.DiGraph()
        
        # 定义虚拟起点和终点
        START = "Start"
        END = "End"
        
        G.add_node(START)
        G.add_node(END)
        
        # 添加每个动作节点的事件点及内部耗时边
        for node_id, node in self.nodes.items():
            start_event = f"S_{node_id}"
            end_event = f"E_{node_id}"
            
            G.add_node(start_event)
            G.add_node(end_event)
            
            # 内部耗时边: S_i -> E_i，权重为动作耗时
            G.add_edge(start_event, end_event, weight=node.duration)
            
            # 默认起止边: 保证所有节点至少从 0 开始，且都对整机 CT 产生贡献
            G.add_edge(START, start_event, weight=0.0)
            G.add_edge(end_event, END, weight=0.0)

        # 添加依赖关系边
        for dep in self.dependencies:
            pred_id = dep.predecessor_id
            succ_id = dep.successor_id
            
            if dep.dep_type == DependencyType.FS:
                # Finish-to-Start: 前置结束 -> 后置开始
                pred_event = f"E_{pred_id}"
                succ_event = f"S_{succ_id}"
                G.add_edge(pred_event, succ_event, weight=dep.delay)
            elif dep.dep_type == DependencyType.SS:
                # Start-to-Start: 前置开始 -> 后置开始
                pred_event = f"S_{pred_id}"
                succ_event = f"S_{succ_id}"
                G.add_edge(pred_event, succ_event, weight=dep.delay)

        # 2. 环路检测 (验证是否为 DAG)
        if not nx.is_directed_acyclic_graph(G):
            # 找出冲突环路
            cycles = list(nx.simple_cycles(G))
            # 格式化环路信息便于用户理解
            formatted_cycles = []
            for cycle in cycles:
                formatted_cycle = " -> ".join(cycle)
                formatted_cycles.append(formatted_cycle)
            raise ValueError(f"检测到循环依赖，无法计算！冲突环路: {formatted_cycles}")

        # 3. 计算单源最长路径 (SSLP)
        # 获取拓扑排序
        topo_order = list(nx.topological_sort(G))
        
        # 初始化最长路径距离
        distances = {v: -float("inf") for v in G.nodes}
        distances[START] = 0.0
        
        # 记录父节点以重建关键路径
        parents = {v: None for v in G.nodes}
        
        # 递推计算
        for u in topo_order:
            if distances[u] == -float("inf"):
                continue
            for v in G.neighbors(u):
                weight = G[u][v]["weight"]
                if distances[u] + weight > distances[v]:
                    distances[v] = distances[u] + weight
                    parents[v] = u

        # 4. 提取结果
        node_times = {}
        for node_id in self.nodes:
            s_time = distances[f"S_{node_id}"]
            e_time = distances[f"E_{node_id}"]
            node_times[node_id] = {
                "start": s_time,
                "end": e_time
            }

        cycle_time = distances[END]

        # 5. 重建关键路径
        event_path = []
        curr = END
        while curr is not None:
            event_path.append(curr)
            curr = parents[curr]
        event_path.reverse()

        # 将事件路径映射回动作节点 ID，去重并保持拓扑顺序
        critical_path = []
        for event in event_path:
            if event in (START, END):
                continue
            # 事件名称为 "S_{node_id}" 或 "E_{node_id}"，前两个字符为 "S_" 或 "E_"
            node_id = event[2:]
            if not critical_path or critical_path[-1] != node_id:
                critical_path.append(node_id)

        return {
            "node_times": node_times,
            "cycle_time": cycle_time,
            "critical_path": critical_path
        }


def calculate_uph(ct_ms: float, units_per_cycle: int = 1, efficiency: float = 1.0) -> float:
    """
    根据整机周期（CT，单位：毫秒）计算每小时产出（UPH，Units Per Hour）。
    
    公式: UPH = (3600 * 1000 / CT_ms) * 每周期产出数量 * 设备效率
    
    参数:
        ct_ms: 整机周期（ms）
        units_per_cycle: 每个周期产出的产品数量（默认为 1）
        efficiency: 设备效率/稼动率（0.0 ~ 1.0，默认为 1.0，即 100%）
        
    返回:
        UPH 值（件/小时）
    """
    if ct_ms <= 0:
        raise ValueError("整机周期 (CT) 必须大于 0 ms")
    return (3_600_000.0 / ct_ms) * units_per_cycle * efficiency
