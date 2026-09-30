from backend.agents.base import BaseAgent
from backend.agents.decoder import DecoderAgent
from backend.agents.explorer import ExplorerAgent
from backend.agents.librarian import LibrarianAgent
from backend.agents.master import MasterAgent
from backend.agents.solver import SolverAgent
from backend.agents.tracker import TrackerAgent

ProjectAnalyzerAgent = ExplorerAgent
RequestAnalyzerAgent = DecoderAgent
CheckerAgent = TrackerAgent
ResourceAgent = LibrarianAgent
TeacherAgent = MasterAgent

__all__ = [
    "BaseAgent",
    "CheckerAgent",
    "DecoderAgent",
    "ExplorerAgent",
    "LibrarianAgent",
    "MasterAgent",
    "ProjectAnalyzerAgent",
    "RequestAnalyzerAgent",
    "ResourceAgent",
    "SolverAgent",
    "TeacherAgent",
    "TrackerAgent",
]
