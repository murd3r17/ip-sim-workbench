"""知识库抽象与 AnythingLLM 适配层。"""

from modules.knowledge.anythingllm import AnythingLLMKnowledgeProvider
from modules.knowledge.local_provider import LocalKnowledgeProvider
from modules.knowledge.provider import KnowledgeProvider
from modules.knowledge.service import KnowledgeService

__all__ = [
    "AnythingLLMKnowledgeProvider",
    "KnowledgeProvider",
    "KnowledgeService",
    "LocalKnowledgeProvider",
]
