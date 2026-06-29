"""pipeline — 판정 파이프라인 오케스트레이션 레이어.

메시지 인입 → 정책 실행 → 에스컬레이션 결정 → 감사로그.
허용 import: core
금지 import: interfaces, 외부 프레임워크 직접 의존(adapters를 통해서만)
"""
