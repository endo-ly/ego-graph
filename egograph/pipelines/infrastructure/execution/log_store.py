"""Local log file persistence."""

from __future__ import annotations

from pathlib import Path


class LocalLogStore:
    """step log をローカルファイルへ保存する。"""

    def __init__(self, logs_root: Path) -> None:
        self._logs_root = logs_root

    def write_step_log(
        self,
        *,
        workflow_id: str,
        run_id: str,
        step_id: str,
        attempt_no: int,
        stdout_text: str,
        stderr_text: str,
    ) -> str:
        """stdout/stderr を1つのログファイルとして保存する。"""
        log_dir = self._logs_root / workflow_id / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{step_id}-attempt{attempt_no}.log"
        log_path.write_text(
            "\n".join(
                [
                    "[stdout]",
                    stdout_text.rstrip(),
                    "",
                    "[stderr]",
                    stderr_text.rstrip(),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return str(log_path)

    @staticmethod
    def tail(text: str, max_chars: int = 4000) -> str:
        """API/DB 保存用に末尾だけ返す。"""
        if len(text) <= max_chars:
            return text
        return text[-max_chars:]

    @staticmethod
    def read_log(log_path: str) -> str:
        """ログ本文を読み込む。"""
        return Path(log_path).read_text(encoding="utf-8")
