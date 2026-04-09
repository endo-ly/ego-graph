"""In-process test steps."""

import time

from pipelines.domain.workflow import WorkflowRun


def succeed() -> dict:
    """成功するテスト step。"""
    print("dummy step succeeded")
    return {"message": "ok"}


def fail() -> None:
    """失敗するテスト step。"""
    print("dummy step failed")
    raise RuntimeError("boom")


def echo_run_summary(run: WorkflowRun) -> dict:
    """run.result_summary を返すテスト step。"""
    print(f"summary={run.result_summary}")
    return run.result_summary or {}


def sleep_too_long() -> None:
    """timeout テスト用に長時間 sleep する。"""
    time.sleep(10)


def sleep_briefly() -> dict:
    """並列実行テスト用に短時間 sleep する。"""
    time.sleep(0.5)
    return {"slept": True}
