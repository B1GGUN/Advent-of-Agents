# Day 02: YAML 驱动的工具调用 Agent

使用 YAML 配置文件定义 Agent 的行为和工具，通过 Anthropic SDK 调用 DeepSeek 模型，实现基于工具调用的智能数学助手。

## 架构概览

```
agent.yaml          ←  定义 Agent 身份、模型、提示词、工具
main.py             ←  读取配置、实现工具、处理对话流程

用户提问 → 模型判断是否需要工具 → 调用工具 → 返回结果 → 输出回答
```

## 核心文件

### agent.yaml — Agent 配置

```yaml
name: math_agent
model: deepseek-v4-pro
max_tokens: 1024
system_prompt: |
  你是一个数学助手。如果用户的问题需要计算，你必须调用 calculate 工具。
  不要直接心算，一定要使用工具。
tools:
  - name: calculate
    description: 计算数学表达式
    parameters:
      type: object
      properties:
        expression:
          type: string
          description: 数学表达式，如 "123 * 456"
      required: [expression]
```

| 字段 | 说明 |
|------|------|
| `name` | Agent 标识名 |
| `model` | 使用的模型（此处为 DeepSeek V4 Pro） |
| `max_tokens` | 模型单次回复最大 token 数 |
| `system_prompt` | 系统提示词，告诉模型它的角色和规则 |
| `tools` | 工具定义列表，包含名称、描述和 JSON Schema 参数 |

### main.py — 运行流程

```
读取 YAML → 创建客户端 → 定义工具实现 → 转换工具格式 →
构建消息 → 调用模型 → 执行工具 → 二次调用 → 输出结果
```

**1. 配置加载**

```python
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "agent.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
```

使用 `__file__` 定位脚本所在目录，无论从哪个路径运行都能正确找到配置文件。

**2. 客户端创建**

```python
api_key = "your-api-key"
client = Anthropic(api_key=api_key)
```

直接传入 API key 创建 Anthropic 客户端。模型名称从 YAML 的 `config["model"]` 动态读取。

**3. 工具实现与映射**

```python
def calculate(expression: str) -> str:
    return str(eval(expression))

tool_map = {"calculate": calculate}
```

YAML 定义工具的**接口**（名称、参数），Python 实现工具的**逻辑**。`tool_map` 将两者关联。

**4. 工具格式转换**

```python
tools = [
    {
        "name": t["name"],
        "description": t["description"],
        "input_schema": t["parameters"]
    }
    for t in config["tools"]
]
```

YAML 中的工具定义 → Anthropic SDK 要求的 tools 格式。

**5. 工具调用循环**

```python
response = client.messages.create(...)

if response.stop_reason == "tool_use":
    # 提取工具调用请求
    tool_use = next(block for block in response.content if block.type == "tool_use")
    # 执行工具
    result = tool_map[tool_use.name](**tool_use.input)
    # 将结果追加到对话
    messages.append(...)
    # 二次调用模型生成最终回答
    final = client.messages.create(...)
```

关键点：
- 通过 `response.stop_reason` 判断模型是否需要调用工具
- `response.content` 中可能包含 `ThinkingBlock`（思考过程）和 `ToolUseBlock`（工具调用），需要用 `block.type` 筛选
- 工具结果以 `tool_result` 格式返回给模型

**6. 输出文本提取**

```python
final_text = next(block.text for block in final.content if block.type == "text")
```

DeepSeek 模型会返回 `ThinkingBlock`（思考过程），需要跳过它，只取 `TextBlock`。

## 运行方式

```bash
cd "Advent of Agents-D2"
python main.py
```

输出示例：
```
123 × 456 = 56088
```

## 关键概念

### 工具调用 (Tool Calling)

模型不会自己计算，而是生成一个工具调用请求，由代码实际执行：

```
用户: "123 * 456 是多少？"
模型: 我不心算，让我调用 calculate({"expression": "123 * 456"})
代码: eval("123 * 456") → 56088
模型: 结果是 56088
```

### YAML 驱动的优势

- **配置与代码分离**：修改模型、提示词、工具定义不改代码
- **可读性强**：YAML 天然适合描述 Agent 配置
- **易于扩展**：新增工具只需在 YAML 加一段定义 + Python 加一个函数

### YAML vs Python 中的工具

| 层 | 位置 | 职责 |
|----|------|------|
| 接口定义 | agent.yaml `tools` | 告诉模型"有什么工具、怎么用" |
| 逻辑实现 | main.py 函数 | 实际执行工具操作 |
| 映射关系 | main.py `tool_map` | 把工具名和函数绑定 |

## D1 → D2 演进

| | D1 | D2 |
|------|-----|-----|
| 配置方式 | 硬编码在代码中 | YAML 配置文件 |
| 工具定义 | Python 字典 | YAML + JSON Schema |
| 可维护性 | 改配置需改代码 | 改配置只动 YAML |
| 工具数量 | 1 个 | 易于扩展多个 |

