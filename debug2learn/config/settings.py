"""
Configuration management for Debug2Learn.

Loads settings from environment variables and .env files.
Provides centralized configuration for all agents and components.
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv


# Session data directory name (created inside target projects)
SESSION_DIR = ".debug2learn"

# Default file extensions to analyze
PYTHON_EXTENSIONS = {".py"}

# Files/directories to always ignore during analysis
IGNORE_PATTERNS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".debug2learn",
    ".egg-info",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

# Maximum file size to analyze (bytes)
MAX_FILE_SIZE = 100_000  # 100KB

# Maximum number of files to analyze in initial scan
MAX_FILES_INITIAL_SCAN = 200

# Maximum tokens for context window management
MAX_CONTEXT_TOKENS = 30_000


@dataclass
class GroqConfig:
    """Configuration for the Groq API."""
    api_key: str = ""
    model: str = "llama-3.3-70b-versatile"
    temperature: float = 0.3
    max_output_tokens: int = 8192


@dataclass
class AppConfig:
    """Main application configuration."""
    groq: GroqConfig = field(default_factory=GroqConfig)
    log_level: str = "INFO"
    project_path: Path = field(default_factory=lambda: Path.cwd())
    session_dir: str = SESSION_DIR

    @property
    def session_path(self) -> Path:
        """Path to the .debug2learn session directory inside the target project."""
        return self.project_path / self.session_dir


def load_config(project_path: Path | None = None) -> AppConfig:
    """
    Load configuration from environment variables and .env file.
    
    Priority:
    1. Environment variables (highest)
    2. .env file in the project directory
    3. .env file in the Debug2Learn installation directory
    4. Defaults (lowest)
    """
    # Load .env from project path if provided
    if project_path:
        env_file = project_path / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    
    # Load project-level configuration and support a .env placed in the active venv.
    package_root = Path(__file__).resolve().parents[2]
    for env_file in (package_root / ".env", Path(sys.prefix) / ".env"):
        if env_file.exists():
            load_dotenv(env_file, override=False)
    
    # Load from environment
    load_dotenv(override=False)

    groq_config = GroqConfig(
        api_key=os.getenv("GROQ_API_KEY", ""),
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=float(os.getenv("GROQ_TEMPERATURE", "0.3")),
        max_output_tokens=int(os.getenv("GROQ_MAX_OUTPUT_TOKENS", "8192")),
    )

    config = AppConfig(
        groq=groq_config,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        project_path=project_path or Path.cwd(),
    )

    return config


def validate_config(config: AppConfig) -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []
    
    if not config.groq.api_key:
        errors.append(
            "GROQ_API_KEY is not set. "
            "Set it in your .env file or as an environment variable."
        )
    
    if not config.project_path.exists():
        errors.append(f"Project path does not exist: {config.project_path}")
    
    return errors
