"""In-process test steps."""

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
