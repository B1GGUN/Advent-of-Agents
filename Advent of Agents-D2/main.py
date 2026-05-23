import os
import yaml
from anthropic import Anthropic


def main():
    # 1. 读取 YAML 配置文件，获取模型、提示词、工具定义
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "agent.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 2. 创建 Anthropic 客户端（传入 API key 和可选代理地址）
    api_key = "your_api_key"
    base_url = None  # 如需代理，填代理地址
    client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)

    # 3. 定义工具的具体实现函数
    def calculate(expression: str) -> str:
        """计算数学表达式"""
        return str(eval(expression))

    # 4. 建立工具名称到实现函数的映射
    tool_map = {"calculate": calculate}

    # 5. 把 YAML 中的工具定义转换为 SDK 要求的格式
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"]
        }
        for t in config["tools"]
    ]

    # 6. 构建初始对话消息（用户提问）
    messages = [{"role": "user", "content": "123 * 456 是多少？"}]

    # 7. 第一次调用模型：模型决定是否需要调用工具
    response = client.messages.create(
        model=config["model"],
        max_tokens=config["max_tokens"],
        system=config["system_prompt"],
        tools=tools,
        messages=messages
    )

    # 8. 根据模型返回的 stop_reason 判断是否需要调用工具
    if response.stop_reason == "tool_use":
        # 8a. 提取模型返回的工具调用请求
        tool_use = next(block for block in response.content if block.type == "tool_use")

        # 8b. 执行工具函数，获取计算结果
        result = tool_map[tool_use.name](**tool_use.input)

        # 8c. 把模型的工具调用响应追加到对话历史
        messages.append({"role": "assistant", "content": response.content})

        # 8d. 把工具执行结果也追加到对话历史
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": result}]
        })

        # 8e. 第二次调用模型：模型根据工具结果生成最终回答
        final = client.messages.create(
            model=config["model"],
            max_tokens=config["max_tokens"],
            system=config["system_prompt"],
            tools=tools,
            messages=messages
        )

        # 8f. 跳过 ThinkingBlock（思考过程），提取最终的文本回复
        final_text = next(block.text for block in final.content if block.type == "text")
        print(final_text)
    else:
        # 9. 模型直接回答了问题（不需要工具），直接输出文本
        response_text = next(block.text for block in response.content if block.type == "text")
        print(response_text)


if __name__ == "__main__":
    main()
