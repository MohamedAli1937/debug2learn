# 🎮 Debug2Learn — AI Debugging Tutor (MVP)

> **Debug2Learn does not replace the developer's thinking. It strengthens it.**

An AI-powered debugging tutor and quest that teaches software developers and students how to find and fix bugs instead of giving away automated answers. Built with **Google Gemini**.

---

## 🎯 Philosophy

Traditional AI assistants work like this:
```text
Developer has a bug ──▶ AI generates fix ──▶ Developer copies code (no learning)
```

**Debug2Learn** works like this:
```text
Developer has a bug ──▶ AI analyzes relevant files ──▶ AI constructs debugging quest
                   ──▶ AI guides with Socratic questions ──▶ Developer thinks & edits code
                   ──▶ AI detects developer changes ──▶ AI evaluates progress
                   ──▶ AI provides progressive hints ──▶ Developer masters the concept!
```

---

## 👥 The 6 AI Game Companions

| Companion | Badge | Role |
| :--- | :---: | :--- |
| **Explorer** | 🧭 | Scans & explores relevant project files, functions, and architecture |
| **Decoder** | 🔐 | Deconstructs bug reports, error messages, and stack traces |
| **Solver** | 🧩 | Diagnoses root cause & constructs a pedagogical debugging plan |
| **Tracker** | 🎯 | Monitors developer modifications in relevant files and diffs |
| **Librarian** | 📚 | Dispatches curated official documentation and learning resources |
| **Master** | 👑 | Guides the developer with Socratic questions and progressive hints |

---

## 💡 Simple Progressive Hint System

Instead of overwhelming the developer or spoiling the answer, the 👑 **Master** delivers hints in 3 progressive stages:

1. **Level 1 (Nudge)**: Conceptual question challenging baseline assumptions.
2. **Level 2 (Clue)**: Directional guidance pointing at suspect variables or control flow.
3. **Level 3 (Direct Clue)**: Explicit mechanism clue without writing the fix.

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone or navigate to the repository
cd Debug2Learn

# Install dependencies
pip install -r requirements.txt

# Configure your Gemini API Key
cp .env.example .env
# Open .env and add: GEMINI_API_KEY=your_key_here
```

### 2. Start the Interactive Debugging Quest

```bash
python main.py
```

### 3. Interactive Commands

During the debugging session, you can interact with your companions:

- `hint` (or `h`): Ask 👑 **Master** for the next progressive hint
- `check` (or `c`): Have 🎯 **Tracker** inspect your edits and 👑 **Master** evaluate your progress
- `plan` (or `p`): Review the 🧩 **Solver**'s quest steps
- `resources` (or `r`): Read 📚 **Librarian**'s curated guides and documentation links
- `ask <question>`: Chat directly with 👑 **Master** using Socratic dialogue
- `quit` (or `q`): Complete the quest

---

## 🏗️ Project Architecture

```text
Debug2Learn/
├── main.py                     # Interactive CLI runner
├── requirements.txt            # Minimal pip dependencies
├── .env.example                # Environment template
├── debug2learn/
│   ├── agents/                 # The 6 Game Companions
│   │   ├── explorer.py         # 🧭 Explorer
│   │   ├── decoder.py          # 🔐 Decoder
│   │   ├── solver.py           # 🧩 Solver
│   │   ├── tracker.py          # 🎯 Tracker
│   │   ├── librarian.py        # 📚 Librarian
│   │   ├── master.py           # 👑 Master
│   │   └── base.py             # Shared Gemini LLM infrastructure
│   ├── analyzers/              # Deterministic code analyzers
│   │   ├── ast_analyzer.py     # AST function, class, and symbol comparison
│   │   ├── file_scanner.py     # Fast directory scanner & filtering
│   │   └── git_analyzer.py     # Git diff & status tracker
│   ├── core/
│   │   ├── models.py           # Lean Pydantic data models
│   │   └── state.py            # Fast in-memory state manager
│   ├── config/
│   │   └── settings.py         # App & Gemini configurations
│   └── utils/
│       └── display.py          # Rich terminal formatting & badges
└── tests/                      # Pytest unit tests (43 passing)
```

---

## 🧪 Running Tests

```bash
pytest
```
