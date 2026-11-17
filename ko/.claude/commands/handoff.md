<!-- source: .claude/commands/handoff.md sha256:e869bca8751542897a151c4ef8232cb87ab31e14daedd716298c95d3d14219b3 source-of-truth: en -->
# 넘기기

지금 하던 일을 다른 세션이나 런타임에 넘긴다. 주제나 넘길 곳이 주어졌다면: "$ARGUMENTS".

`system/rituals.md#handoff`를 따른다. 넘김 메모를 `_private/state/handoff/` 아래에 쓰고, 그 경로를 가리키는
한 줄을 `python3 tools/now.py log --private`로 기록하고, 스레드에 서류철이 있으면 거기에 다섯 줄을 덧붙인다.

그다음 메모의 경로를 한 줄로 알린다. 메모 내용을 대화에 요약하지 않는다. 다음 세션은 파일을 읽는다.
