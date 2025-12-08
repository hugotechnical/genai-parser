import re


def to_markdown(text: str) -> str:
    """Normalize plain text into simple Markdown formatting."""
    text = text.replace("\r", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"•|- ", "- ", text)
    text = text.strip()
    return text


