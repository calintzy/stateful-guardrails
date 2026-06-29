"""ISC-2.6: split 동결·누수 차단.

검증:
  1. 동결 파라미터 5종(t1·t2·λ·K·N·S_max)이 calibration.json에 존재.
  2. calibration.json이 calibration-split(c3.calib)에서 파생되고 test-split 미사용 명시.
  3. calib-split 세션 ID가 test-split에 누수되지 않음 (C1·C3 양쪽).
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"

FROZEN_KEYS = ["threshold_t1", "threshold_t2", "lambda_decay",
               "window_size_k", "state_window_n", "s_max"]


def _session_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["session_id"])
    return ids


def test_frozen_params_present():
    """calibration.json에 동결 파라미터 5종(+t2)이 모두 존재한다."""
    calib = json.loads((_DATA / "calibration.json").read_text(encoding="utf-8"))
    for key in FROZEN_KEYS:
        assert key in calib, f"동결 파라미터 누락: {key}"
    # 동결 값 검증 (지정된 값)
    assert calib["lambda_decay"] == 0.7
    assert calib["window_size_k"] == 5
    assert calib["state_window_n"] == 10
    assert calib["s_max"] == 1.0


def test_calibration_derived_from_calib_split_only():
    """calibration.json이 calibration-split에서 파생되고 test-split 미사용을 명시한다."""
    calib = json.loads((_DATA / "calibration.json").read_text(encoding="utf-8"))
    assert "calib" in calib["calibration_split"], "calibration이 calib-split 파생이 아님"
    assert "test" not in calib["calibration_split"].split("/")[-1].replace("calib", ""), \
        "calibration_split 경로에 test 흔적"
    assert "test-split" in calib["test_split_note"]
    assert "미사용" in calib["test_split_note"]


def test_c3_calib_test_session_ids_disjoint():
    """C3 calib·test 세션 ID가 겹치지 않는다 (누수 0)."""
    calib_ids = _session_ids(_DATA / "c3.calib.jsonl")
    test_ids = _session_ids(_DATA / "c3.test.jsonl")
    overlap = calib_ids & test_ids
    assert not overlap, f"C3 split 세션ID 누수: {overlap}"


def test_c1_calib_test_session_ids_disjoint():
    """C1 calib·test 세션 ID가 겹치지 않는다 (누수 0)."""
    calib_ids = _session_ids(_DATA / "c1.calib.jsonl")
    test_ids = _session_ids(_DATA / "c1.test.jsonl")
    overlap = calib_ids & test_ids
    assert not overlap, f"C1 split 세션ID 누수: {overlap}"


def test_all_session_ids_globally_unique():
    """전체 데이터셋에서 세션 ID가 전역 고유하다."""
    all_ids: list[str] = []
    for fn in ["c1.calib.jsonl", "c1.test.jsonl", "c3.calib.jsonl", "c3.test.jsonl"]:
        path = _DATA / fn
        if path.exists():
            all_ids.extend(_session_ids(path))
    assert len(all_ids) == len(set(all_ids)), "세션 ID 전역 중복 발견"


def test_split_field_matches_filename():
    """각 세션의 split 필드가 파일명과 일치한다 (라벨 무결성)."""
    for fn, expected in [
        ("c1.calib.jsonl", "calib"), ("c1.test.jsonl", "test"),
        ("c3.calib.jsonl", "calib"), ("c3.test.jsonl", "test"),
    ]:
        path = _DATA / fn
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    assert d.get("split") == expected, (
                        f"{fn}: split 필드 불일치 {d.get('split')} != {expected}"
                    )
