"""实训模块路由测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestTrainingEndpoints:
    """路由层端到端测试（mock DB）"""

    @pytest.mark.asyncio
    async def test_list_labs_endpoint(self):
        from modules.training.router import list_labs
        # 构建正确的mock链: db.execute() -> result.scalars() -> .all()
        mock_scalar_result = MagicMock()
        mock_scalar_result.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalar_result
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_user = {"user_id": 1, "username": "test", "role": "admin"}
        result = await list_labs(db=mock_db, current_user=mock_user)
        assert result == []
