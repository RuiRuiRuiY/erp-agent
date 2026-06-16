"""Mock LLM 工厂：用于替代真实 LLM 进行单元测试。"""
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage


def make_mock_llm(responses: list[AIMessage]) -> MagicMock:
    """创建 mock LLM，responses 是按调用顺序返回的 AIMessage 列表。"""
    call_idx = [0]

    async def mock_ainvoke(messages, **kwargs):
        idx = min(call_idx[0], len(responses) - 1)
        call_idx[0] += 1
        return responses[idx]

    mock_llm = MagicMock()
    mock_llm.ainvoke = mock_ainvoke
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return mock_llm
