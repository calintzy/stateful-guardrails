"""adapters.state_store — SessionState JSON 영속화 (D-1).

core.state.StateStore Protocol을 구현한다.
경량 KV(JSON 파일) 영속성 — 프로세스 재시작 후 상태 복원(ISC-2.2).
NG-4: SQLite/JSON 수준 영속성, 풀 DB 아님.

레이어 규칙: 파일 I/O는 adapters에서만.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from stateful_guardrails.core.policy import SessionState


class JSONStateStore:
    """세션 상태를 디렉토리 내 JSON 파일로 영속화한다.

    파일 경로: {root}/{session_id}.json
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        # 세션 ID를 파일명으로 안전하게 사용 (영숫자·언더스코어·하이픈 외 전부 치환)
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id)
        return self._root / f"{safe}.json"

    def get(self, session_id: str) -> SessionState | None:
        """세션 상태를 로드한다. 파일이 없으면 None."""
        path = self._path(session_id)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return SessionState(
            session_id=data["session_id"],
            policy_scores=dict(data.get("policy_scores", {})),
            turn_count=data.get("turn_count", 0),
            lambda_decay=data.get("lambda_decay", 0.7),
            s_max=data.get("s_max", 1.0),
        )

    def put(self, state: SessionState) -> None:
        """세션 상태를 JSON 파일로 영속화한다."""
        path = self._path(state.session_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, ensure_ascii=False, indent=2)
