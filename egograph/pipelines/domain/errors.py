"""Pipelines domain errors."""


class PipelinesError(Exception):
    """pipelines サービスの基底例外。"""


class WorkflowNotFoundError(PipelinesError):
    """指定された workflow が存在しない。"""


class WorkflowDisabledError(PipelinesError):
    """workflow が無効化されているため実行できない。"""


class WorkflowRunNotFoundError(PipelinesError):
    """指定された workflow run が存在しない。"""


class StepRunNotFoundError(PipelinesError):
    """指定された step run が存在しない。"""


class WorkflowLockUnavailableError(PipelinesError):
    """workflow lock を取得できない。"""
