import os
import sys
import yaml
import warnings
from typing import Optional
import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic

# 抑制 urllib3 的 SSL 警告
warnings.filterwarnings("ignore", message=".*urllib3.*")


# ---------- 搜索引擎实现 ----------

# 模拟浏览器请求头，避免被反爬
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def search_bing(query: str) -> Optional[str]:
    """通过 Bing 搜索，返回格式化结果"""
    url = "https://www.bing.com/search"
    resp = requests.get(url, params={"q": query}, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.b_algo")
    if not items:
        return None

    lines = [f"[Bing 搜索结果] 共 {len(items)} 条"]
    for i, item in enumerate(items[:5], 1):
        title_tag = item.select_one("h2 a")
        title = title_tag.get_text(strip=True) if title_tag else "无标题"
        href = title_tag.get("href", "") if title_tag else ""
        desc_tag = item.select_one(".b_caption p") or item.select_one(".b_lineclamp2")
        desc = desc_tag.get_text(strip=True) if desc_tag else "无摘要"
        lines.append(f"{i}. {title}\n   {desc}\n   {href}")
    return "\n\n".join(lines)


def search_baidu(query: str) -> Optional[str]:
    """通过百度搜索，返回格式化结果"""
    url = "https://www.baidu.com/s"
    resp = requests.get(url, params={"wd": query}, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("div.result, div.c-result")
    if not items:
        # 新版百度页面结构
        items = soup.select("div.c-container")

    if not items:
        return None

    lines = [f"[百度搜索结果] 共 {len(items)} 条"]
    for i, item in enumerate(items[:5], 1):
        title_tag = item.select_one("h3 a")
        title = title_tag.get_text(strip=True) if title_tag else "无标题"
        href = title_tag.get("href", "") if title_tag else ""
        desc_tag = item.select_one("span.content-right_8Zs40") or \
                   item.select_one("div.c-abstract") or \
                   item.select_one("span.c-color-text")
        desc = desc_tag.get_text(strip=True) if desc_tag else "无摘要"
        lines.append(f"{i}. {title}\n   {desc}\n   {href}")
    return "\n\n".join(lines)


# ---------- 工具实现 ----------

def calculate(expression: str) -> str:
    """计算数学表达式"""
    try:
        return str(eval(expression))
    except Exception as e:
        return f"计算出错: {e}"


def web_search(query: str) -> str:
    """搜索互联网：优先使用 Bing，失败时回退到百度"""
    # 1. 优先使用 Bing（支持中文，反爬较宽松）
    result = search_bing(query)
    if result:
        return result

    # 2. Bing 失败则回退到百度
    result = search_baidu(query)
    if result:
        return result

    return f"所有搜索引擎均无法获取关于 '{query}' 的结果，请稍后重试"


# ---------- 主流程 ----------

def main():
    # 1. 读取 YAML 配置文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "agent.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 2. 创建 Anthropic 客户端
    api_key = "your_api_key"
    base_url = None
    client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)

    # 3. 工具名称到实现函数的映射
    tool_map = {
        "calculate": calculate,
        "web_search": web_search,
    }

    # 4. 把 YAML 中的工具定义转换为 SDK 格式
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"]
        }
        for t in config["tools"]
    ]

    # 5. 从命令行获取用户问题，默认为天气查询
    if len(sys.argv) > 1:
        user_question = " ".join(sys.argv[1:])
    else:
        user_question = input("请输入你的问题: ")
    messages = [{"role": "user", "content": user_question}]

    # 6. 对话循环：限制最大搜索轮数，避免无限查询
    max_rounds = 3
    final_response = None

    for round_num in range(1, max_rounds + 1):
        response = client.messages.create(
            model=config["model"],
            max_tokens=config["max_tokens"],
            system=config["system_prompt"],
            tools=tools,
            messages=messages
        )

        # 7. 模型需要调用工具 → 执行工具
        if response.stop_reason == "tool_use":
            tool_uses = [block for block in response.content if block.type == "tool_use"]

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_use in tool_uses:
                tool_name = tool_use.name
                tool_args = tool_use.input

                result = tool_map[tool_name](**tool_args)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

            # 到达最大轮数时，强制要求模型总结
            if round_num == max_rounds:
                messages.append({
                    "role": "user",
                    "content": "你已经搜索了多轮，请基于以上所有搜索结果，直接给出总结回答，不要再搜索了。"
                })
                final_response = client.messages.create(
                    model=config["model"],
                    max_tokens=config["max_tokens"],
                    system=config["system_prompt"],
                    tools=tools,
                    messages=messages
                )

        # 8. 模型直接回复 → 保存并退出循环
        else:
            final_response = response
            break

    # 9. 输出最终回答
    if final_response:
        final_text = next(block.text for block in final_response.content if block.type == "text")
        print(f"\n{final_text}")
    else:
        print("\n未能获取回答，请重试")


if __name__ == "__main__":
    main()
