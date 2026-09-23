from __future__ import annotations

import argparse
from pathlib import Path

from dtia.web import run


def main() -> None:
    parser = argparse.ArgumentParser(description="DataTech Image Archives — Local")
    parser.add_argument("--data-dir", type=Path, help="Pasta alternativa para banco e miniaturas")
    parser.add_argument("--port", type=int, default=8148, help="Porta local (padrão: 8148)")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador automaticamente")
    arguments = parser.parse_args()
    run(arguments.data_dir, arguments.port, not arguments.no_browser)


if __name__ == "__main__":
    main()

