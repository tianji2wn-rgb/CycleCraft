# CycleCraft — 自动化设备动作时序图计算软件

一个轻量级的 Python 工具，用于评估自动化设备在多工位、多工序并行/串行情况下的**整机周期 (CT)** 和 **UPH (Units Per Hour)**。  
提供 NiceGUI 交互式 Web 界面，支持可视化甘特图、节点依赖关系图、关键路径高亮及项目持久化。

---

## 核心特性

- **动作节点定义** — 支持动作 ID、名称、所属工位/轴、标准耗时
- **两种依赖关系**：
  - **FS (Finish-to-Start)** — 前置动作结束后，当前动作开始（可设延时）
  - **SS (Start-to-Start)** — 前置动作开始时，当前动作同时开始（可设延时）
- **并行处理** — 多个动作同时依赖同一前置节点时自动并行执行
- **事件级 DAG 引擎** — 基于 NetworkX 构建事件级有向无环图，支持复杂混合时序计算
- **关键路径分析** — 自动识别瓶颈工序链（Critical Path）
- **UPH 换算** — 支持按设备稼动率计算理论产能
- **交互式 Web GUI** — 甘特图、节点依赖关系图、数据表格全联动

---

## 安装

本项目使用 [uv](https://github.com/astral-sh/uv) 管理依赖。

```bash
# 克隆仓库
git clone https://github.com/tianji2wn-rgb/CycleCraft.git
cd CycleCraft

# 创建虚拟环境并安装依赖
uv venv
uv sync
```

---

## 运行

### CLI 演示

```bash
uv run main.py
```

输出动作时序表、CT、UPH 及关键路径。

### Web 界面

```bash
uv run gui.py
```

启动后访问 `http://127.0.0.1:8080`，可进行：

- 📊 **甘特图** — 堆叠柱状图展示各动作的绝对时间，红色标记关键路径
- 🔗 **节点依赖关系图** — 泳道布局，蓝色实线=FS，绿色虚线=SS，红色=关键路径
- 📋 **数据表格** — 支持双击内联编辑耗时、添加/编辑/删除动作节点
- 💾 **项目管理** — 新建、保存、打开项目（JSON 格式持久化）
- 📈 **实时看板** — CT、UPH、关键路径实时更新

---

## 项目结构

```
CycleCraft/
├── src/
│   └── cyclecraft/
│       ├── __init__.py          # 包导出
│       ├── models.py            # 数据模型：ActionNode, Dependency, DependencyType
│       └── engine.py            # DAG 计算引擎：SequenceCalculator, calculate_uph
├── main.py                      # CLI 演示脚本
├── gui.py                       # NiceGUI Web 界面
├── projects/                    # 项目文件存储目录
├── pyproject.toml               # 项目配置与依赖声明
└── uv.lock                      # 依赖锁文件
```

---

## 数据模型

### ActionNode

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 唯一标识 |
| `name` | str | 动作名称 |
| `station` | str | 所属工位/轴 |
| `duration` | float | 标准耗时 (ms) |

### Dependency

| 字段 | 类型 | 说明 |
|------|------|------|
| `predecessor_id` | str | 前置节点 ID |
| `successor_id` | str | 后置节点 ID |
| `dep_type` | DependencyType | `FS` 或 `SS` |
| `delay` | float | 延时 (ms)，默认 0 |

---

## 依赖

- Python 3.8+
- [NetworkX](https://networkx.org/) — DAG 构建与拓扑排序
- [NiceGUI](https://nicegui.io/) — Web 界面框架

---

## 许可证

MIT License
