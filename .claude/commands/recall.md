`python3 tools/recall.py find "$ARGUMENTS"` 로 과거 대화 원문을 회상해줘.
결과를 통째로 붓지 말고 현재 논의에 묶인 몇 줄로 번역할 것 (PRD-session-memory §3.4).
매치가 없으면 known-item 실패로 journal에 기록해 (임베딩 게이트 카운트).
