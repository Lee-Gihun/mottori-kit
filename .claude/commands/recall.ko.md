<!-- source: recall.md sha256:d4ca940aa59bb1c9839001867c80d070e07f9bf0017a28c478059b2a311cf3b1 source-of-truth: en -->
# 회상

`python3 tools/recall.py find "$ARGUMENTS"` 로 과거 대화 원문을 회상해줘.
결과를 통째로 붓지 말고 현재 논의에 묶인 몇 줄로 번역할 것 (PRD-session-memory §3.4).
매치가 없으면 known-item 실패로 journal에 기록해 (임베딩 게이트 카운트).
