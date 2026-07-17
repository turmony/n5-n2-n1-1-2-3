"""Aggregate immutable quiz attempts into learner-facing reports."""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalyticsSummary:
    by_item_type: Counter
    by_error_tag: Counter


def aggregate_attempts(attempts: list[dict]) -> AnalyticsSummary:
    return AnalyticsSummary(
        Counter(item["item_type"] for item in attempts if not item.get("is_correct")),
        Counter(tag for item in attempts if not item.get("is_correct") for tag in item.get("error_tags", [])),
    )


def render_daily_report(summary: AnalyticsSummary, due: int, overdue: int, deferred: int, limit: int) -> str:
    weak = "、".join(name for name, _ in summary.by_item_type.most_common(3)) or "暂无作答数据"
    return f"# 今日复习\n\n- 上限：{limit}\n- 到期：{due}\n- 逾期：{overdue}\n- 未排入：{deferred}\n- 薄弱题型：{weak}\n"
