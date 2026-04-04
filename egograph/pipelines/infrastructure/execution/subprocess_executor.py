"""Subprocess step execution."""

from __future__ import annotations

import subprocess

from pipelines.domain.workflow import (
    StepDefinition,
    StepExecutionResult,
    StepRunStatus,
    WorkflowRun,
)
from pipelines.infrastructure.execution.log_store import LocalLogStore


class SubprocessStepExecutor:
    """StepDefinition.command を subprocess で実行する。"""

    def __init__(self, log_store: LocalLogStore) -> None:
        self._log_store = log_store

    def execute(
        self,
        *,
        workflow_id: str,
        run: WorkflowRun,
        step: StepDefinition,
        attempt_no: int,
    ) -> StepExecutionResult:
        """subprocess を実行し、ログと終了状態を返す。"""
        try:
            completed = subprocess.run(
                list(step.command),
                capture_output=True,
                text=True,
                timeout=step.timeout_seconds,
                check=False,
            )
            stdout_text = completed.stdout or ""
            stderr_text = completed.stderr or ""
            log_path = self._log_store.write_step_log(
                workflow_id=workflow_id,
                run_id=run.run_id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            )
            return StepExecutionResult(
                status=StepRunStatus.SUCCEEDED
                if completed.returncode == 0
                else StepRunStatus.FAILED,
                exit_code=completed.returncode,
                stdout_tail=self._log_store.tail(stdout_text),
                stderr_tail=self._log_store.tail(stderr_text),
                log_path=log_path,
                result_summary=None,
                error_message=None
                if completed.returncode == 0
                else f"command failed with exit code {completed.returncode}",
            )
        except subprocess.TimeoutExpired as exc:
            stdout_text = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr_text = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            log_path = self._log_store.write_step_log(
                workflow_id=workflow_id,
                run_id=run.run_id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            )
            return StepExecutionResult(
                status=StepRunStatus.FAILED,
                exit_code=None,
                stdout_tail=self._log_store.tail(stdout_text),
                stderr_tail=self._log_store.tail(stderr_text),
                log_path=log_path,
                result_summary=None,
                error_message=f"command timed out after {step.timeout_seconds}s",
            )
