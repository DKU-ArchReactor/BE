# ArchReactor: An Educational RISC-V Architecture Simulator for Computer Engineering Freshmen

## Backend deployment

`core` 브랜치의 AWS Elastic Beanstalk 배포와 새 계정 설정은
[배포 가이드](docs/aws/beanstalk.md)를 참고하세요.

- 시연용 HTTPS API: https://d1j3nkcez6kncs.cloudfront.net/
- Swagger: https://d1j3nkcez6kncs.cloudfront.net/docs

브라우저→CloudFront→Beanstalk 서버까지 HTTPS이며, 원본 인증서는 자동 갱신됩니다.

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
