"""Google Health repair schedule定義のテスト。"""

from pipelines.workflows.registry import get_workflows


def test_google_health_repair_schedules_have_expected_windows():
    """3種類のrepair jobが同じworkflowへ期待期間を渡す。"""
    workflow = get_workflows()["google_health_ingest_workflow"]

    schedules = {
        trigger.schedule_name: trigger for trigger in workflow.triggers
    }

    assert set(schedules) == {
        "google_health_same_day_repair",
        "google_health_daily_repair",
        "google_health_weekly_repair",
    }
    assert schedules["google_health_same_day_repair"].trigger_expr == "3h"
    assert schedules["google_health_same_day_repair"].result_summary == {
        "request": {"repair_days": 2}
    }
    assert schedules["google_health_daily_repair"].trigger_expr == "30 4 * * *"
    assert schedules["google_health_daily_repair"].result_summary == {
        "request": {"repair_days": 14}
    }
    assert schedules["google_health_weekly_repair"].trigger_expr == "30 5 * * sun"
    assert schedules["google_health_weekly_repair"].result_summary == {
        "request": {"repair_days": 45}
    }
    assert all(trigger.use_service_timezone for trigger in schedules.values())
