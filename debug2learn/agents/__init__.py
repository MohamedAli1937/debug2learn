"""
Debug2Learn Game Agents.

The 6 Game Agents:
🧭 Explorer   - Explores & understands relevant project files
🔐 Decoder    - Decodes & parses bug reports and stack traces
🧩 Solver     - Analyzes root causes and constructs debugging plans
🎯 Tracker    - Tracks developer modifications in relevant files
📚 Librarian  - Curates targeted documentation and learning resources
👑 Master     - Socratic mentor providing progressive hints and guidance
"""

from debug2learn.agents.base import BaseAgent
from debug2learn.agents.decoder import DecoderAgent
from debug2learn.agents.explorer import ExplorerAgent
from debug2learn.agents.librarian import LibrarianAgent
from debug2learn.agents.master import MasterAgent
from debug2learn.agents.solver import SolverAgent
from debug2learn.agents.tracker import TrackerAgent

# Backwards compatibility aliases
ProjectAnalyzerAgent = ExplorerAgent
RequestAnalyzerAgent = DecoderAgent
CheckerAgent = TrackerAgent
ResourceAgent = LibrarianAgent
TeacherAgent = MasterAgent

__all__ = [
    "BaseAgent",
    "ExplorerAgent",
    "DecoderAgent",
    "SolverAgent",
    "TrackerAgent",
    "LibrarianAgent",
    "MasterAgent",
    # Aliases
    "ProjectAnalyzerAgent",
    "RequestAnalyzerAgent",
    "CheckerAgent",
    "ResourceAgent",
    "TeacherAgent",
]
