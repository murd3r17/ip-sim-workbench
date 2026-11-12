"""MetricAggregator 聚合与清理测试（C-08：改为真实 SQL 断言，不再断言 mock 调用次数）。

历史问题：整份用例把聚合 SELECT 的结果用 MagicMock 造出来，只断言
`db.add` 被调用几次 —— 聚合 SQL 写错、幂等删除漏掉、SUM/AVG 语义反了都测不出来。
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.database import Base
from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
from modules.monitor.models import AggLevel, MetricAggregated, MetricRecord, MetricType
from modules.monitor.service import MetricAggregator

HOUR = datetime(2026, 6, 15, 10, 0, 0)


@pytest_asyncio.fixture(autouse=True)
async def _isolate(test_engine):
    """这些用例直接用 test_session_factory（内存库 session 级共享），必须自己清表。"""
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


async def _seed_device(db, hostname: str = "agg-r1") -> Device:
    topology = Topology(name=f"topo-{hostname}", topology_type=TopologyType.LAB, status="active")
    db.add(topology)
    await db.flush()
    device = Device(
        hostname=hostname,
        mgmt_ip="198.51.100.71",
        device_type=DeviceType.ROUTER,
        vendor=DeviceVendor.HUAWEI,
        status=DeviceStatus.ONLINE,
        topology_id=topology.id,
    )
    db.add(device)
    await db.flush()
    return device


def _record(device_id: int, value: float, collected_at: datetime, metric: MetricType = MetricType.CPU_USAGE):
    return MetricRecord(
        device_id=device_id,
        metric_type=metric,
        metric_name="",
        value=value,
        unit="%",
        collected_at=collected_at,
    )


class TestSqlitePrimaryKeys:
    @pytest.mark.asyncio
    async def test_bigint_primary_keys_autoincrement_on_sqlite(self, test_session_factory):
        """最小模式（SQLite）下 metric_record 的 BIGINT 主键必须能自增。

        SQLite 只把 INTEGER PRIMARY KEY 当作 rowid 别名；BIGINT PRIMARY KEY 不会自动
        赋值，此前最小模式插入监控数据会直接 NOT NULL constraint failed —— 整条采集
        链路在 SQLite 下全废，而测试全用 MagicMock 所以从未暴露。
        """
        async with test_session_factory() as db:
            device = await _seed_device(db, "agg-pk")
            record = _record(device.id, 12.5, HOUR)
            db.add(record)
            await db.flush()
            assert record.id is not None

            created = await MetricAggregator(db).aggregate_hourly(HOUR)
            assert created == 1
            row = (await db.execute(select(MetricAggregated))).scalars().one()
            assert row.id is not None


class TestAggregateHourly:
    @pytest.mark.asyncio
    async def test_hourly_aggregation_uses_real_rows(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _seed_device(db)
            db.add_all([
                _record(device.id, 40.0, HOUR.replace(minute=5)),
                _record(device.id, 80.0, HOUR.replace(minute=35)),
                _record(device.id, 60.0, HOUR.replace(minute=55)),
                # 区间外：不应被计入
                _record(device.id, 999.0, HOUR - timedelta(minutes=1)),
            ])
            await db.commit()

            created = await MetricAggregator(db).aggregate_hourly(HOUR)

            assert created == 1
            row = (
                await db.execute(select(MetricAggregated).where(MetricAggregated.agg_level == AggLevel.HOURLY))
            ).scalars().one()

        assert row.device_id == device.id
        assert row.metric_type == MetricType.CPU_USAGE
        assert row.min_value == 40.0
        assert row.max_value == 80.0
        assert row.avg_value == 60.0
        assert row.sample_count == 3
        assert row.period_start == HOUR
        assert row.period_end == HOUR.replace(minute=59, second=59)

    @pytest.mark.asyncio
    async def test_hourly_aggregation_is_idempotent(self, test_session_factory):
        """重复聚合同一小时不能重复累计样本（P0-34 的回归点）。"""
        async with test_session_factory() as db:
            device = await _seed_device(db, "agg-r2")
            db.add_all([_record(device.id, 10.0, HOUR.replace(minute=1))])
            await db.commit()

            aggregator = MetricAggregator(db)
            await aggregator.aggregate_hourly(HOUR)
            await aggregator.aggregate_hourly(HOUR)

            rows = (
                await db.execute(select(MetricAggregated).where(MetricAggregated.agg_level == AggLevel.HOURLY))
            ).scalars().all()

        assert len(rows) == 1
        assert rows[0].sample_count == 1

    @pytest.mark.asyncio
    async def test_hourly_no_data_creates_nothing(self, test_session_factory):
        async with test_session_factory() as db:
            created = await MetricAggregator(db).aggregate_hourly(HOUR)
            rows = (await db.execute(select(MetricAggregated))).scalars().all()
        assert created == 0
        assert rows == []

    @pytest.mark.asyncio
    async def test_hourly_groups_per_device_and_metric(self, test_session_factory):
        async with test_session_factory() as db:
            first = await _seed_device(db, "agg-r3")
            second = await _seed_device(db, "agg-r4")
            db.add_all([
                _record(first.id, 30.0, HOUR.replace(minute=1)),
                _record(first.id, 50.0, HOUR.replace(minute=2)),
                _record(second.id, 70.0, HOUR.replace(minute=3)),
                _record(second.id, 90.0, HOUR.replace(minute=4), MetricType.MEMORY_USAGE),
            ])
            await db.commit()

            created = await MetricAggregator(db).aggregate_hourly(HOUR)
            rows = (
                await db.execute(select(MetricAggregated).where(MetricAggregated.agg_level == AggLevel.HOURLY))
            ).scalars().all()

        assert created == 3
        by_key = {(r.device_id, r.metric_type): r for r in rows}
        assert by_key[(first.id, MetricType.CPU_USAGE)].avg_value == 40.0
        assert by_key[(second.id, MetricType.CPU_USAGE)].avg_value == 70.0
        assert by_key[(second.id, MetricType.MEMORY_USAGE)].sample_count == 1


class TestAggregateDaily:
    @pytest.mark.asyncio
    async def test_daily_rolls_up_hourly_rows(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _seed_device(db, "agg-r5")
            day = HOUR.replace(hour=0, minute=0, second=0)
            for hour in (0, 1, 2):
                db.add_all([
                    _record(device.id, 10.0 + hour, day.replace(hour=hour, minute=5)),
                    _record(device.id, 20.0 + hour, day.replace(hour=hour, minute=30)),
                ])
            await db.commit()

            aggregator = MetricAggregator(db)
            for hour in (0, 1, 2):
                await aggregator.aggregate_hourly(day.replace(hour=hour))

            created = await aggregator.aggregate_daily(day)
            daily = (
                await db.execute(select(MetricAggregated).where(MetricAggregated.agg_level == AggLevel.DAILY))
            ).scalars().one()

        assert created == 1
        assert daily.min_value == 10.0
        assert daily.max_value == 22.0
        assert daily.sample_count == 6  # 3 小时 × 2 条
        assert daily.period_start == day

    @pytest.mark.asyncio
    async def test_daily_is_idempotent(self, test_session_factory):
        async with test_session_factory() as db:
            device = await _seed_device(db, "agg-r6")
            day = HOUR.replace(hour=0, minute=0, second=0)
            db.add_all([_record(device.id, 10.0, day.replace(hour=1, minute=5))])
            await db.commit()

            aggregator = MetricAggregator(db)
            await aggregator.aggregate_hourly(day.replace(hour=1))
            await aggregator.aggregate_daily(day)
            await aggregator.aggregate_daily(day)

            rows = (
                await db.execute(select(MetricAggregated).where(MetricAggregated.agg_level == AggLevel.DAILY))
            ).scalars().all()

        assert len(rows) == 1
        assert rows[0].sample_count == 1

    @pytest.mark.asyncio
    async def test_daily_without_hourly_data_creates_nothing(self, test_session_factory):
        async with test_session_factory() as db:
            created = await MetricAggregator(db).aggregate_daily(HOUR.replace(hour=0, minute=0, second=0))
        assert created == 0


class TestCleanupOldRecords:
    @pytest.mark.asyncio
    async def test_cleanup_removes_only_expired_rows(self, test_session_factory, monkeypatch):
        from core.config import get_settings

        async with test_session_factory() as db:
            device = await _seed_device(db, "agg-r7")
            now = datetime.now()
            db.add_all([
                _record(device.id, 1.0, now - timedelta(days=40)),   # 过期
                _record(device.id, 2.0, now - timedelta(days=1)),    # 保留
            ])
            db.add_all([
                MetricAggregated(
                    device_id=device.id, metric_type=MetricType.CPU_USAGE, agg_level=AggLevel.HOURLY,
                    period_start=now - timedelta(days=90), period_end=now - timedelta(days=90),
                    min_value=1.0, max_value=1.0, avg_value=1.0, sample_count=1,
                    created_at=now - timedelta(days=90),
                ),
                MetricAggregated(
                    device_id=device.id, metric_type=MetricType.CPU_USAGE, agg_level=AggLevel.HOURLY,
                    period_start=now - timedelta(days=10), period_end=now - timedelta(days=10),
                    min_value=1.0, max_value=1.0, avg_value=1.0, sample_count=1,
                    created_at=now - timedelta(days=10),
                ),
            ])
            await db.commit()

            settings = get_settings()
            monkeypatch.setattr(settings, "monitor_retention_days", 30)

            result = await MetricAggregator(db).cleanup_old_records()
            raw_left = (await db.execute(select(MetricRecord))).scalars().all()
            agg_left = (await db.execute(select(MetricAggregated))).scalars().all()

        assert result["raw_deleted"] == 1
        assert result["agg_deleted"] == 1  # 聚合保留期是原始数据的两倍（60 天）
        assert len(raw_left) == 1
        assert len(agg_left) == 1

    @pytest.mark.asyncio
    async def test_cleanup_with_nothing_expired(self, test_session_factory, monkeypatch):
        from core.config import get_settings

        async with test_session_factory() as db:
            device = await _seed_device(db, "agg-r8")
            db.add(_record(device.id, 1.0, datetime.now() - timedelta(days=1)))
            await db.commit()

            settings = get_settings()
            monkeypatch.setattr(settings, "monitor_retention_days", 30)

            result = await MetricAggregator(db).cleanup_old_records()

        assert result["raw_deleted"] == 0
        assert result["agg_deleted"] == 0
