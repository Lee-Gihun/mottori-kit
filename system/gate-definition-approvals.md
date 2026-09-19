# Gate-definition approvals (append-only)

One line per approved gate-definition diff (KIT-DR-013). `tools/manifest_build.py --issues` accepts a diff only when a
line matches its sorted file list and sha256 exactly. Lines are never edited or removed; a new diff gets a new line.

gate-definition-approval: decision:KIT-DR-013 files=.github/workflows/gates.yml,system/enforcement-matrix.yaml,system/review-manifest.yaml,system/test-matrix.yaml,tools/evidencecheck.py,tools/gate.py,tools/manifest_build.py,tools/test_language.py sha256=3c4bd837ddf4d465a54999f9416f6199b4643f5d6d1458642ab1c48a16d598c8
gate-definition-approval: decision:KIT-DR-013 files=.github/workflows/gates.yml,system/review-manifest.yaml,system/test-matrix.yaml,tools/manifest_build.py,tools/test_language.py sha256=f95ec5573a91bb9ac0b72730f5c61640d02de0d3d2b6516f4e1dfbaf057a4b5e
gate-definition-approval: decision:KIT-DR-013 files=tools/gate.py sha256=a4cc85fb23497833e3283ab03aef2bc5858052a121fe1a7b3f00869e518c358c
gate-definition-approval: decision:KIT-DR-014 files=system/enforcement-matrix.yaml,system/review-manifest.yaml,system/test-matrix.yaml sha256=afd06f5b15e225543061cba60786bb1ca163f18d00de7edf35a4c133f0b7a189
