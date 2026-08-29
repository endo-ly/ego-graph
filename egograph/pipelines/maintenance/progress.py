"""長時間実行される保守処理の進捗出力。"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TextIO


class ProgressReporter:
    """保守処理の進捗を通知するインターフェース。"""

    def report(self, phase: str, current: int, total: int, label: str) -> None:
        """1処理単位の進捗を通知する。"""
        raise NotImplementedError


@dataclass
class StderrProgressReporter(ProgressReporter):
    """進捗をstderrへ1行ずつ出力する。"""

    stream: TextIO = field(default_factory=lambda: sys.stderr)

    def report(self, phase: str, current: int, total: int, label: str) -> None:
        """stdoutのJSON出力を汚さず進捗を出力する。"""
        print(f"[{phase}] {current}/{total} {label}", file=self.stream)


class NullProgressReporter(ProgressReporter):
    """進捗を破棄するテスト・ライブラリ利用向け実装。"""

    def report(self, phase: str, current: int, total: int, label: str) -> None:
        """何もしない。"""


__all__ = [
    "NullProgressReporter",
    "ProgressReporter",
    "StderrProgressReporter",
]
