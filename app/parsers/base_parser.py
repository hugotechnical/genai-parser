from abc import ABC, abstractmethod
from app.models import ParsedResult

class BaseParser(ABC):
    """Interface for all parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> ParsedResult:
        """Return file content as Markdown string."""
        raise NotImplementedError


