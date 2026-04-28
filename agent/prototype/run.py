"""
Entrypoint del prototipo A.5.

Ejemplos:

    python run.py --provider claude --task "abre Firefox y busca allAI OS"
    python run.py --provider ollama --model qwen2.5vl:7b --task "..."
    python run.py --provider claude --benchmark
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import claude_loop
import ollama_loop


BENCHMARK_TASKS: list[tuple[str, str]] = [
    ("open_firefox", "Abre la aplicación Firefox."),
    ("navigate_url", "En Firefox, navega a https://duckduckgo.com."),
    ("search_term", "En el motor de búsqueda abierto, busca el texto 'allAI OS' y presiona Enter."),
    ("terminal_uname", "Abre una Terminal y ejecuta el comando 'uname -a'."),
    ("create_text_file", "Abre el editor de texto, crea un archivo con el contenido 'hola allAI' y guárdalo en /tmp/hello.txt."),
    ("take_screenshot", "Toma un screenshot del escritorio y guárdalo como ~/Pictures/test.png usando la app Captura de pantalla."),
    ("change_wallpaper", "Abre Configuración → Fondos y elige cualquier wallpaper diferente al actual."),
    ("read_resolution", "Abre Configuración → Pantalla y dime cuál es la resolución actual de la pantalla principal."),
    ("count_conf", "Abre Files (Nautilus), navega a /etc, y dime aproximadamente cuántos archivos terminan en .conf."),
    ("close_all", "Cierra todas las ventanas abiertas."),
]


def _make_log_dir(root: Path, label: str) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_dir = root / f"{ts}-{label}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _run_claude(task: str, model: str, log_dir: Path) -> dict:
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("ERROR: ANTHROPIC_API_KEY no está definido.", file=sys.stderr)
        sys.exit(2)
    cfg = claude_loop.RunConfig(task=task, model=model, log_dir=log_dir)
    result = claude_loop.run(cfg)
    return _result_to_dict(result)


def _run_ollama(task: str, model: str, log_dir: Path, host: str | None) -> dict:
    cfg = ollama_loop.RunConfig(task=task, model=model, log_dir=log_dir, host=host)
    result = ollama_loop.run(cfg)
    return _result_to_dict(result)


def _result_to_dict(result) -> dict:
    return {
        "success": result.success,
        "iterations": result.iterations,
        "duration_s": round(result.duration_s, 2),
        "tool_calls": result.tool_calls,
        "final_text": result.final_text,
        "error": result.error,
    }


def _benchmark(provider: str, model: str, host: str | None, root: Path) -> None:
    overall_label = f"benchmark-{provider}"
    overall_dir = _make_log_dir(root, overall_label)
    summary_path = overall_dir / "report.md"

    results: list[tuple[str, str, dict]] = []
    started = time.monotonic()

    for label, task in BENCHMARK_TASKS:
        print(f"\n=== {label}: {task}")
        log_dir = overall_dir / label
        if provider == "claude":
            r = _run_claude(task, model, log_dir)
        else:
            r = _run_ollama(task, model, log_dir, host)
        print(f"   -> success={r['success']} iters={r['iterations']} t={r['duration_s']}s")
        results.append((label, task, r))
        # respiro entre tareas para que el sistema regrese a estado neutral
        time.sleep(3)

    duration_total = time.monotonic() - started
    success_count = sum(1 for _, _, r in results if r["success"])

    lines = [
        f"# Benchmark del prototipo — {provider}",
        "",
        f"- Modelo: `{model}`",
        f"- Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Resultado: **{success_count}/{len(results)}** tareas completadas",
        f"- Duración total: {duration_total:.1f}s",
        "",
        "## Detalle",
        "",
        "| Tarea | Éxito | Iteraciones | Tool calls | Duración (s) | Error |",
        "|-------|-------|-------------|------------|--------------|-------|",
    ]
    for label, task, r in results:
        lines.append(
            f"| {label} | {'✅' if r['success'] else '❌'} | {r['iterations']} | "
            f"{r['tool_calls']} | {r['duration_s']} | {r['error'] or ''} |"
        )
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReporte: {summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prototipo Computer Use de allAI OS")
    parser.add_argument("--provider", choices=["claude", "ollama"], required=True)
    parser.add_argument("--model", default=None, help="Modelo a usar")
    parser.add_argument("--task", help="Tarea en lenguaje natural (omitir si --benchmark)")
    parser.add_argument("--benchmark", action="store_true", help="Ejecuta las 10 tareas estándar")
    parser.add_argument("--ollama-host", default=None, help="URL de Ollama (default: http://localhost:11434)")
    parser.add_argument("--logs", default="prototype-runs", help="Carpeta de logs")
    args = parser.parse_args()

    if not args.benchmark and not args.task:
        parser.error("--task o --benchmark requerido")

    root = Path(args.logs)

    if args.provider == "claude":
        model = args.model or claude_loop.DEFAULT_MODEL
        if args.benchmark:
            _benchmark("claude", model, None, root)
        else:
            log_dir = _make_log_dir(root, "claude")
            r = _run_claude(args.task, model, log_dir)
            print(r)
    else:
        model = args.model or ollama_loop.DEFAULT_MODEL
        if args.benchmark:
            _benchmark("ollama", model, args.ollama_host, root)
        else:
            log_dir = _make_log_dir(root, "ollama")
            r = _run_ollama(args.task, model, log_dir, args.ollama_host)
            print(r)


if __name__ == "__main__":
    main()
