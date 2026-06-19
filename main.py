import sys
import os

# 确保 Windows 控制台中文输出不乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 将 src 目录加入 Python 搜索路径，确保可以直接运行此脚本
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from cyclecraft import SequenceCalculator, ActionNode, DependencyType, calculate_uph

def run_simulation():
    print("=" * 60)
    print(" 开始运行 CycleCraft 自动化设备动作时序图计算引擎验证 ")
    print("=" * 60)
    
    # 1. 初始化计算引擎
    calculator = SequenceCalculator()

    # 2. 定义动作节点（气缸推料 -> 相机拍照 -> 机械手搬运，含并行/延时动作）
    # 节点定义参数：id, name, station, duration (单位: ms)
    nodes = [
        ActionNode("1", "气缸推料", "气缸推料工位", 200.0),
        ActionNode("2", "相机拍照", "视觉检测工位", 150.0),
        ActionNode("3", "吹气除尘", "视觉检测工位", 100.0),
        ActionNode("4", "气缸复位", "气缸推料工位", 150.0),
        ActionNode("5", "机械手吸取", "机械手搬运工位", 300.0),
        ActionNode("6", "机械手搬运", "机械手搬运工位", 500.0),
    ]

    for node in nodes:
        calculator.add_node(node)
        print(f"已添加节点: [{node.station}] {node.name} (ID: {node.id}) | 标准耗时: {node.duration} ms")

    print("-" * 60)

    # 3. 添加依赖关系
    # A. 气缸推料结束后，相机拍照立即开始 (FS, delay=0)
    calculator.add_dependency("1", "2", DependencyType.FS, delay=0.0)
    print("已添加依赖: 气缸推料 -(FS, delay=0ms)-> 相机拍照")

    # B. 相机拍照开始后 20ms，吹气除尘动作开始 (SS, delay=20)
    calculator.add_dependency("2", "3", DependencyType.SS, delay=20.0)
    print("已添加依赖: 相机拍照 -(SS, delay=20ms)-> 吹气除尘 (并行)")

    # C. 相机拍照结束后，气缸即可复位 (FS, delay=0) (可与机械手动作并行)
    calculator.add_dependency("2", "4", DependencyType.FS, delay=0.0)
    print("已添加依赖: 相机拍照 -(FS, delay=0ms)-> 气缸复位 (并行)")

    # D. 相机拍照结束后，等待 50ms（防抖或信号延时），机械手开始吸取 (FS, delay=50)
    calculator.add_dependency("2", "5", DependencyType.FS, delay=50.0)
    print("已添加依赖: 相机拍照 -(FS, delay=50ms)-> 机械手吸取")

    # E. 机械手吸取完成后，立即开始搬运 (FS, delay=0)
    calculator.add_dependency("5", "6", DependencyType.FS, delay=0.0)
    print("已添加依赖: 机械手吸取 -(FS, delay=0ms)-> 机械手搬运")

    print("-" * 60)

    # 4. 执行时序计算
    try:
        results = calculator.calculate()
    except ValueError as e:
        print(f"计算失败: {e}")
        return

    # 5. 打印计算结果
    node_times = results["node_times"]
    cycle_time = results["cycle_time"]
    critical_path = results["critical_path"]

    print("\n[ 计算结果 - 动作时间表 ]")
    print(f"{'动作ID':<15} {'动作名称':<10} {'工位':<12} {'标准耗时(ms)':<10} {'绝对开始(ms)':<10} {'绝对结束(ms)':<10}")
    print("-" * 80)
    for node_id, times in node_times.items():
        node = calculator.nodes[node_id]
        print(f"{node_id:<17} {node.name:<12} {node.station:<14} {node.duration:<12.1f} {times['start']:<12.1f} {times['end']:<12.1f}")
    
    print("-" * 80)

    # 6. 计算 UPH 换算
    uph_100 = calculate_uph(cycle_time, units_per_cycle=1, efficiency=1.0)
    uph_85 = calculate_uph(cycle_time, units_per_cycle=1, efficiency=0.85)

    print(f"\n[ 整机周期与产能评估 ]")
    print(f"  - 整机单次循环周期 (Cycle Time): {cycle_time:.1f} ms ({cycle_time / 1000.0:.3f} s)")
    print(f"  - 理论产能 UPH (100% 效率): {uph_100:.2f} Pcs/Hour")
    print(f"  - 实际产能 UPH (85% 稼动率): {uph_85:.2f} Pcs/Hour")

    # 7. 打印关键路径
    print(f"\n[ 关键路径 (Critical Path / 瓶颈工序) ]")
    path_str = " -> ".join([f"{calculator.nodes[nid].name}({nid})" for nid in critical_path])
    print(f"  {path_str}")
    print("=" * 60)

if __name__ == "__main__":
    run_simulation()
