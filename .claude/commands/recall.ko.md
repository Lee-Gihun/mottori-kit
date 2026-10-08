<!-- source: recall.md sha256:2adf86c730bfa242d74c1615e4927915204ac22b9df69dad8867bec30926514b source-of-truth: en -->
# 회상

`python3 tools/recall.py find "$ARGUMENTS"` 로 과거 대화 원문을 회상해줘.
결과를 통째로 붓지 말고 현재 논의에 묶인 몇 줄로 번역할 것 (system/PRD-session-memory.md#retrieval).
원문이 존재함을 아는 질의에서 못 찾았을 때만 known-item 실패로 journal에 기록해.
원인은 소스 가용성·파서·필터·랭킹·표현 불일치로 나눠 확인하고, 모르면 미확인으로 남겨.
일반적인 검색 0건을 곧바로 known-item 실패나 원문 부재로 세지 마.
