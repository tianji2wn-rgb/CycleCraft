from enum import Enum
from dataclasses import dataclass

class DependencyType(Enum):
    """
    依赖关系类型枚举。
    """
    FS = "FS"  # Finish-to-Start：前置动作结束后，当前动作立即开始（支持延迟）
    SS = "SS"  # Start-to-Start：前置动作开始时，当前动作同时开始（支持延迟）

@dataclass
class ActionNode:
    """
    动作节点类，表示时序图中的一个具体动作步骤。
    """
    id: str         # 唯一标识
    name: str       # 动作名称
    station: str    # 所属工位/轴
    duration: float # 标准耗时（单位：ms）

@dataclass
class Dependency:
    """
    节点之间的依赖关系定义。
    """
    predecessor_id: str             # 前置节点唯一标识
    successor_id: str               # 后置（当前）节点唯一标识
    dep_type: DependencyType        # 前置关系类型 (FS / SS)
    delay: float = 0.0              # 延时（单位：ms）
