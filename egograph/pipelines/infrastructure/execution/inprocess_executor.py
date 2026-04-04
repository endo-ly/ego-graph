"""In-process step execution."""

from __future__ import annotations

import importlib
import inspect
import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Callable

from pipelines.domain.workflow import (
    StepDefinition,
    StepExecutionResult,
    StepRunStatus,
    WorkflowRun,
)
from pipelines.infrastructure.execution.log_store import LocalLogStore


class InProcessStepExecutor:
    """StepDefinition.callable_ref を Python 関数として実行する。"""

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
        """callable_ref を import して実行する。"""
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            target = self._load_callable(step.callable_ref)
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                result = self._invoke(target, run)
            stdout_text = stdout_buffer.getvalue()
            stderr_text = stderr_buffer.getvalue()
            log_path = self._log_store.write_step_log(
                workflow_id=workflow_id,
                run_id=run.run_id,
                step_id=step.step_id,
                attempt_no=attempt_no,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            )
            return StepExecutionResult(
                status=StepRunStatus.SUCCEEDED,
                exit_code=0,
                stdout_tail=self._log_store.tail(stdout_text),
                stderr_tail=self._log_store.tail(stderr_text),
                log_path=log_path,
                result_summary=result if isinstance(result, dict) else None,
            )
        except Exception as exc:
            stdout_text = stdout_buffer.getvalue()
            stderr_text = stderr_buffer.getvalue() + f"\n{type(exc).__name__}: {exc}"
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
                exit_code=1,
                stdout_tail=self._log_store.tail(stdout_text),
                stderr_tail=self._log_store.tail(stderr_text),
                log_path=log_path,
                result_summary=None,
                error_message=str(exc),
            )

    @staticmethod
    def _load_callable(callable_ref: str | None) -> Callable[[], Any]:
        if not callable_ref:
            raise ValueError("callable_ref is required for in-process step")
        module_name, function_name = callable_ref.split(":", maxsplit=1)
        module = importlib.import_module(module_name)
        target = getattr(module, function_name)
        if not callable(target):
            raise TypeError(f"step target is not callable: {callable_ref}")
        return target

    @staticmethod
    def _invoke(target: Callable[..., Any], run: WorkflowRun) -> Any:
        signature = inspect.signature(target)
        if len(signature.parameters) == 0:
            return target()
        return target(run)
