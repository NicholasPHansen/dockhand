import sys

from rich import print as rich_print
from rich.panel import Panel


def error_and_exit(message: str, code: int = 1):
    panel = Panel(message, border_style="red", title="Error", title_align="left", highlight=True)
    rich_print(panel)
    sys.exit(code)
