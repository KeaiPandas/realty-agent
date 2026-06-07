"""情报统计聚合"""
from services.db import get_message_stats, get_kpi_stats


def get_stats() -> dict:
    """获取完整情报统计"""
    kpi = get_kpi_stats()
    msg_stats = get_message_stats()

    return {
        "kpi": kpi,
        "message_distribution": msg_stats["message_distribution"],
        "stage_distribution": msg_stats["stage_distribution"],
        "daily_trend": msg_stats["daily_trend"],
    }
