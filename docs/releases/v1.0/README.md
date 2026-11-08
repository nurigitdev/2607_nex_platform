# NeX Platform v1.0 문서 패키지

이 디렉터리는 태그 `v1.0`, commit `ab7af0fc`를 기준으로 만든 설치·기동·운영·사용 문서의 원본과 배포본을 보관한다.

## 기준과 제한

- 지원 구성: Single-host Docker Compose
- 코드 기준선: `v1.0`
- 현재 release decision: `NO_GO`
- production deployment: 승인되지 않음
- 화면 자료: v1.0 AE Web을 deterministic mock 데이터로 실행하여 Playwright로 생성
- 비밀정보와 실제 사용자 데이터: 포함하지 않음

`NO_GO`는 문서나 구현 실패를 의미하지 않는다. 외부 notification P1 waiver, 네 개 승인 역할, change window가 충족되기 전에는 운영 배포를 실행하지 않는다는 release governance 결과다.

## 원본

| 문서 | Markdown 원본 | 주요 독자 |
| --- | --- | --- |
| 시스템 구축(설치) 절차서 | `source/01_system_installation_guide.md` | 설치 담당자, 플랫폼 관리자 |
| 시스템 기동·종료 절차서 | `source/02_system_startup_shutdown_guide.md` | 시스템 운영자 |
| 시스템 운영 절차서 | `source/03_system_operations_guide.md` | 플랫폼·보안·데이터 운영자 |
| 시스템 사용자 매뉴얼 | `source/04_user_manual.md` | 최종 사용자 |

화면 원본은 `assets/screenshots/`에 PNG로 저장한다. `manifest.json`은 각 이미지의 SHA-256과 v1.0 source revision을 기록한다.

## 재생성

저장소 루트에서 다음 명령을 순서대로 실행한다.

```bash
npm --prefix apps/nex-ae-web run docs:capture-v1
./.venv/bin/python scripts/docs/build_v1_0_manuals.py --summary
```

결과 DOCX와 digest manifest는 `deliverables/`에 생성된다. 화면 생성기는 `apps/nex-ae-web/index.html`과 `apps/nex-ae-web/src`가 v1.0 태그와 다르면 실패한다.

## 배포본 검증

```bash
./.venv/bin/python -m pytest tests/test_v1_0_manuals.py
soffice --headless --convert-to pdf --outdir /tmp/nex-v1-manuals \
  docs/releases/v1.0/deliverables/*.docx
```

DOCX 생성에는 LibreOffice가 필요하지 않다. 마지막 PDF 렌더링 검사는 선택 사항이며 `libreoffice-writer`가 설치된 환경에서 실행한다.

DOCX는 Git에서 직접 편집하지 않는다. 내용을 변경하려면 Markdown 또는 PNG 원본을 수정한 뒤 전체 배포본을 다시 생성한다.
