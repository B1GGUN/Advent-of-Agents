# Day 03: 多工具搜索 Agent

在 D2 的基础上新增搜索引擎工具，Agent 可以自主决定调用「计算」还是「搜索」，支持多轮搜索直至获得满意结果。

## 架构概览

```
agent.yaml          ←  两个工具：calculate + web_search
main.py             ←  搜索引擎实现 + 多轮对话循环 + 轮数限制

用户提问 → 模型判断需要什么工具 → 执行工具 → 结果不够？继续搜索 →
达到最大轮数 → 强制总结 → 输出回答
```

相比 D2 的线性流程（一次调用→执行工具→二次调用），D3 升级为**循环流程**，模型可以在多轮搜索中不断优化关键词。

## 核心文件

### agent.yaml — 双工具配置

```yaml
name: search_agent
model: deepseek-v4-pro
max_tokens: 1024
system_prompt: |
  你是一个全能助手，具备计算和搜索能力。
  - 如果用户的问题需要数学计算，调用 calculate 工具
  - 如果用户的问题需要实时信息（如天气、新闻、最新资讯），调用 web_search 工具
  - 不要猜测或编造你不知道的信息，一定要使用工具获取
  - 搜索最多进行 2-3 轮，如果搜索结果中没有精确数据，
    直接基于已有信息总结回答，不要反复搜索
tools:
  - name: calculate
    ...
  - name: web_search
    description: 搜索互联网获取实时信息
    parameters:
      type: object
      properties:
        query:
          type: string
          description: 搜索查询词
      required: [query]
```

与 D2 的区别：工具列表从一个扩展为两个，system_prompt 中增加了工具选择规则和搜索轮数限制。

### main.py — 新增模块

代码结构分为三层：

| 模块 | 职责 |
|------|------|
| 搜索引擎层 | `search_bing()` + `search_baidu()` — 抓取并解析搜索结果页 |
| 工具实现层 | `calculate()` + `web_search()` — 封装为模型可调用的工具 |
| 主流程层 | `main()` — 对话循环、轮数控制、结果输出 |

**1. 搜索引擎层：requests + BeautifulSoup**

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 ... Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def search_bing(query: str) -> Optional[str]:
    url = "https://www.bing.com/search"
    resp = requests.get(url, params={"q": query}, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.b_algo")  # Bing 搜索结果容器
    # 遍历提取标题、摘要、链接 ...
```

关键技术点：
- **模拟浏览器请求头**（User-Agent + Accept-Language），避免被搜索引擎反爬拦截
- **CSS 选择器定位结果**：Bing 用 `li.b_algo`，百度用 `div.result` / `div.c-container`
- **百度备选选择器**：百度页面结构可能变化，代码中预留了多种 `select` 方案
- **超时控制**：`timeout=15` 防止请求卡死

**2. 搜索引擎回退策略**

```python
def web_search(query: str) -> str:
    result = search_bing(query)  # 优先 Bing
    if result:
        return result
    result = search_baidu(query) # 回退百度
    if result:
        return result
    return "所有搜索引擎均无法获取结果"
```

Bing 作为首选（反爬宽松、中文搜索质量好），百度作为备选（国内覆盖面更广）。

**3. 对话循环：从 if 到 for**

D2 的处理方式（单次工具调用）：
```python
if response.stop_reason == "tool_use":
    # 执行工具 → 二次调用 → 结束
```

D3 升级为循环（支持多轮）：
```python
for round_num in range(1, max_rounds + 1):
    if response.stop_reason == "tool_use":
        # 执行工具 → 将结果追加到对话 → 继续循环
        ...
        if round_num == max_rounds:
            # 追加"请总结"提示 → 调用模型生成最终回答
```

**4. 轮数限制机制**

```
第 1 轮搜索 → 结果不够理想
第 2 轮搜索 → 换关键词再试
第 3 轮搜索 → 还是不精确
          ↓
    追加提示："你已经搜索了多轮，请基于已有结果直接总结，不要再搜索了"
          ↓
    调用模型 → 强制输出总结回答
```

通过 `max_rounds = 3` 和最后一轮的强制总结提示，D2 中可能无限查询的问题不再存在。

**5. 命令行输入**

```python
if len(sys.argv) > 1:
    user_question = " ".join(sys.argv[1:])
else:
    user_question = input("请输入你的问题: ")
```

两种方式：直接传参或交互式输入，方便不同场景使用。

## 运行方式

```bash
# 命令行传参
python3 main.py "南京天气"
python3 main.py "今天有什么科技新闻"
python3 main.py "Python 3.14 新增了哪些特性"

# 交互式输入
python3 main.py
请输入你的问题: 帮我查一下苹果最新股价
```

## 关键概念

### 多工具协作

模型根据用户意图自动选择工具：

```
"123 * 456 是多少？"  →  calculate("123 * 456")
"南京今天天气怎么样？" →  web_search("南京天气")
"Python 3.13 新特性"   →  web_search("Python 3.13 新特性")
```

system_prompt 中明确规则，引导模型在计算和搜索之间正确决策。

### 搜索结果 ≠ 直接答案

搜索引擎抓取的是搜索结果页（链接 + 摘要），不是实时数据的 API。模型需要从摘要中提取有用信息，如果摘要不包含精确数据，模型会给出信息来源链接而非编造答案。这是搜索 Agent 的真实能力边界。

### 轮数限制的重要性

没有限制的对话循环会造成：
- 用户等待时间过长
- API 费用无限增长
- 重复查询相同内容

D3 通过 `max_rounds` + 强制总结提示解决了这个问题。

## D2 → D3 演进

| | D2 | D3 |
|------|-----|-----|
| 工具数量 | 1 个（calculate） | 2 个（calculate + web_search） |
| 对话模式 | 单次 if-else | for 循环，多轮迭代 |
| 搜索引擎 | 无 | Bing（主）+ 百度（备） |
| 用户输入 | 硬编码在代码中 | 命令行参数 + 交互式输入 |
| 最大轮数 | 无限制 | 3 轮 + 强制总结 |
| 新增依赖 | yaml, anthropic | + requests, beautifulsoup4 |
| 反爬处理 | 无 | 浏览器 User-Agent 模拟 |

## 常见问题

**Q: 为什么选择 Bing + 百度，而不是 Google？**

Google 反爬严格，国内访问也不稳定。Bing 支持中文搜索、反爬相对宽松，百度作为国内搜索引擎的备选。两者均无需 API key。

**Q: 搜索结果中为什么经常出现百科类结果而非精确数据？**

搜索引擎返回的是网页链接和摘要，不是结构化数据。天气、股价等实时信息需要搜索引擎将特殊卡片嵌入结果页。Agent 能做的是从已有摘要中提取信息，而非保证每次都有精确答案。

**Q: 怎么知道百度/Bing 的 CSS 选择器是否过时了？**

网页结构变化时解析会返回空结果，此时自动回退到另一个引擎。如果两个引擎都失败，会返回明确的错误提示。排查时可以在 `web_search` 中临时打印 `resp.text[:500]` 查看实际 HTML 结构。

**Q: 为什么不直接用搜索 API（如 SerpAPI）？**

搜索 API 需要付费和 API key。D3 的目标是零成本、零额外配置的通用搜索方案。生产环境中，API 方案更稳定可靠。
