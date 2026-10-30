# ArchReactor: An Educational RISC-V Architecture Simulator for Computer Engineering Freshmen

## Backend deployment

`core` 브랜치의 AWS Elastic Beanstalk 배포와 새 계정 설정은
[배포 가이드](docs/aws/beanstalk.md)를 참고하세요.

- 시연용 HTTPS API: https://d1j3nkcez6kncs.cloudfront.net/
- Swagger: https://d1j3nkcez6kncs.cloudfront.net/docs

브라우저→CloudFront→Beanstalk 서버까지 HTTPS이며, 원본 인증서는 자동 갱신됩니다.

## 로그인·파일 저장 없는 시뮬레이션

이 흐름은 익명 시뮬레이션 기능을 포함한 BE 버전을 배포한 뒤 사용할 수 있습니다.
두 요청 모두 `Content-Type: application/json`을 사용하며 `Authorization`은 생략합니다.

1. `POST /api/v1/build/compile`

   ```json
   {
     "content": "int main(){return 0;}",
     "lang": "c",
     "compiler_opt": "-O0",
     "compile_profile": "rv32im"
   }
   ```

   HTTP 201만으로 컴파일 성공을 판단하지 않습니다. 응답의 `status`가 `success`이고
   `simulation_token`이 있을 때 다음 요청을 보냅니다. 실패하면 `log`를 표시합니다.
   `build_id`는 여전히 `null`이며, `simulation_token_expires_in`은 300(초)입니다.
   `native` 프로파일이나 실패한 빌드에는 실행 토큰을 발급하지 않습니다.

2. `POST /api/v1/simulation/run`

   ```json
   {
     "simulation_token": "빌드 응답의 simulation_token",
     "mode": "pipeline",
     "max_cycles": 2000
   }
   ```

   `mode`는 `single` 또는 `pipeline`, `max_cycles`는 1~2000입니다.
   토큰 유효 기간 내에는 같은 ELF를 두 모드에서 반복 실행할 수 있습니다.
   `execution_status`는 `COMPLETED`, `CYCLE_LIMIT`, `SIMULATION_ERROR`로 구분합니다.
   화면에는 기존과 동일하게 `result.history`, `result.summary`, `result.console_output`을 사용합니다.
   HTTP 410이면 토큰 만료이므로 현재 코드를 다시 빌드하고, 401이면 토큰 오류를 표시합니다.
   HTTP 429는 CORE 자원·결과 크기 제한, 503은 서비스 사용 불가, 504는 실행 시간 초과입니다.

실행 버튼에서 빌드와 시뮬레이션을 순차 호출하고 중복 실행을 막습니다.
익명 경로는 파일·빌드 DB 기록을 만들지 않지만 기존과 같이 결과물을 S3에 저장합니다.
토큰의 5분 만료가 S3 객체 삭제를 뜻하지는 않습니다.
토큰은 실행 권한이므로 URL, 분석 이벤트, 로그에 남기지 않고 클라이언트 메모리에서 취급합니다.
서버는 기존 `JWT_SECRET_KEY`에서 로그인용과 분리된 서명 키를 도출하며,
기본 개발용 키가 설정된 상태에서는 익명 실행 토큰 발급을 거부합니다.

로그인 사용자의 기존 `build_id` 방식도 유지됩니다. `/simulation/run`에는
`build_id`와 `simulation_token` 중 하나만 전달해야 하며, `build_id` 방식에는
기존과 동일하게 로그인과 빌드 소유권 확인이 필요합니다.

**ArchReactor** is an educational RISC-V architecture simulation platform  
designed for computer engineering freshmen.

This project helps students understand how instructions are executed  
inside a CPU, step by step and cycle by cycle.

---

## Architecture Overview

![Arch-Reactor Architecture](architecture.png)

---

## Motivation

Many computer engineering students find it difficult to understand:

- How C or assembly code is executed inside a CPU
- How instructions move through pipeline stages
- Why similar code can have different execution times

ArchReactor was created to visualize these processes clearly  
and help students learn computer architecture more intuitively.

---

## Key Features

- RISC-V (RV32I) instruction simulation
- Pipeline visualization (IF, ID, EX, MEM, WB)
- Cycle-by-cycle execution view
- Register and memory state tracking
- Stall, forwarding, and flush explanation
- Code saving and reloading
- Execution statistics (cycles, CPI)

*(C language support and AI-based optimization advice are planned features.)*

---

## System Architecture

ArchReactor is built with three main components:

- **Core (Python)**  
  - RISC-V instruction execution logic  
  - Pipeline and hazard simulation  

- **Backend (FastAPI)**  
  - API server  
  - Code and execution history management  
  - Core integration  

- **Frontend (React)**  
  - Code editor  
  - Pipeline and state visualization  

---

## Target Users

- Computer Engineering freshmen
- Students learning computer architecture
- Anyone interested in how code runs on hardware

---

## How to Run (Development)

### Frontend
```bash
cd frontend
npm install
npm run dev
```


# BE — ArchReactor Backend

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

→ http://localhost:8000 (API) / http://localhost:8000/docs (Swagger UI)

## Docker 실행

```bash
cp .env.example .env
docker-compose up --build
```

→ http://localhost:8000 (API) / http://localhost:8000/docs (Swagger UI)

종료: `docker-compose down` (DB 데이터 유지) / `docker-compose down -v` (DB 데이터 삭제)
