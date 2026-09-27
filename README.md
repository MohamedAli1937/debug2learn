# Debug2Learn

Debug2Learn is an AI-assisted debugging tutor. It helps developers understand a failure, inspect evidence, form a hypothesis, and validate their own fix instead of silently generating code for them.

The project combines a FastAPI web application, a command-line quest, deterministic code analysis, and Groq-powered teaching agents.

## What It Does

Debug2Learn turns a bug report or test traceback into a guided debugging session:

1. Decode the report and preserve important code tokens.
2. Explore the target project and connect tests to source files.
3. Diagnose the likely root cause and build a learning plan.
4. Recommend focused documentation.
5. Track changes made by the developer.
6. Guide investigation with progressive Socratic questions.
7. Validate the developer's test output.

The system distinguishes a failure location, such as a test, from the implementation that caused the failure.

## Agent Team

| Agent     | Responsibility                                               |
| --------- | ------------------------------------------------------------ |
| Explorer  | Maps files, functions, tests, and source relationships       |
| Decoder   | Extracts symptoms, tracebacks, symbols, and relevant files   |
| Solver    | Identifies root causes and creates a teaching plan           |
| Librarian | Curates resources related to the actual debugging concept    |
| Tracker   | Snapshots files and evaluates developer changes              |
| Master    | Provides Socratic guidance, questions, and progressive hints |

## Requirements

- Python 3.11 or newer
- A Groq API key for AI-generated analysis and conversation
- `pip` and a virtual environment

## Installation

```powershell
cd Debug2Learn
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the repository root:

```env
GROQ_API_KEY=your_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

Never commit `.env` or expose the API key in browser code.

## Run the Web App

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

Enter the absolute path to a project, describe the failure, and use the Master chat to investigate it. The backend must remain running while using the web interface.

## Run the CLI

```powershell
.\.venv\Scripts\python.exe main.py
```

The CLI supports `hint`, `check`, `plan`, `resources`, `ask <question>`, and `quit`.

## Test the Project

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The test suite covers the agents, analyzers, state models, tracker behavior, and the todo debugging workflow.

## Groq and Quota Behavior

Groq is used by the Decoder, Solver, Librarian, and Master when the SDK and API key are available. The default model is `llama-3.3-70b-versatile`; set `GROQ_MODEL` to use another model supported by your account.

When Groq returns a quota or rate-limit error, Debug2Learn does not invent an AI response. The web session stops at startup with an explicit quota message. The local deterministic analyzers remain useful for tests and development, but they are not presented as Groq-generated answers.

If the API reports a `429` quota error, wait for the quota window to reset or review the billing and rate-limit settings for the Groq account.

## GitHub Pages Demo

The static interface is published at:

<https://mohamedali1937.github.io/debug2learn/>

GitHub Pages cannot run the FastAPI backend or safely hold a Groq API key. The published page therefore provides a client-side demonstration. For real Groq-powered debugging, run the local FastAPI server and use <http://127.0.0.1:8000>.

## Repository Layout

```text
Debug2Learn/
├── server.py                  # FastAPI web server
├── main.py                    # Interactive CLI
├── frontend/index.html        # Web interface
├── debug2learn/
│   ├── agents/                # Explorer, Decoder, Solver, Librarian, Tracker, Master
│   ├── analyzers/             # AST, file, and Git analysis
│   ├── config/                # Environment and application settings
│   ├── core/                  # Pydantic models and session state
│   └── utils/                 # Terminal presentation helpers
├── tests/                     # Automated tests
├── requirements.txt
└── .env.example
```

## Design Principles

- Teach the reasoning process rather than conceal it.
- Ground diagnoses in the actual project files and test output.
- Keep deterministic analysis separate from model-generated interpretation.
- Never expose secrets in the frontend.
- Report unavailable AI services honestly instead of fabricating answers.
