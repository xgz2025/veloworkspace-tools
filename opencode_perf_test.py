import time
import argparse
import platform
import subprocess
import os
import statistics
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

def get_environment_info() -> dict:
    info = {}
    is_darwin = platform.system() == "Darwin"

    if is_darwin:
        try:
            info["cpu_type"] = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
        except Exception:
            info["cpu_type"] = platform.processor() or "Apple Silicon"

        try:
            profiler = subprocess.check_output(
                ["system_profiler", "SPHardwareDataType"], stderr=subprocess.DEVNULL
            ).decode("utf-8")
            model_name = "Mac"
            for line in profiler.splitlines():
                if "Model Name:" in line:
                    model_name = line.split("Model Name:")[1].strip()
                    break
            info["mac_type"] = model_name
        except Exception:
            info["mac_type"] = "Mac"

        cores = os.cpu_count() or 1
        info["total_cores"] = f"{cores} Cores"

        try:
            mem_bytes = int(subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], stderr=subprocess.DEVNULL
            ).decode("utf-8").strip())
            info["total_ram"] = f"{mem_bytes / (1024**3):.1f} GB"
        except Exception:
            info["total_ram"] = "Unknown"

        mac_ver = platform.mac_ver()[0]
        info["os_type"] = f"macOS {mac_ver} (Darwin {platform.release()})"

    else:  # Linux Guest VM
        info["cpu_type"] = "vCPU"
        info["mac_type"] = "VM"
        cores = os.cpu_count() or 1
        info["total_cores"] = f"{cores} Cores"

        try:
            mem_pages = os.sysconf('SC_PHYS_PAGES')
            page_size = os.sysconf('SC_PAGE_SIZE')
            mem_bytes = mem_pages * page_size
            info["total_ram"] = f"{mem_bytes / (1024**3):.1f} GB"
        except Exception:
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if 'MemTotal:' in line:
                            kb = int(line.split()[1])
                            info["total_ram"] = f"{kb / (1024**2):.1f} GB"
                            break
            except Exception:
                info["total_ram"] = "Unknown"

        os_distro = "Linux"
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            os_distro = line.split("=", 1)[1].strip().strip('"')
                            break
        except Exception:
            pass
        info["os_type"] = f"{os_distro} (Kernel {platform.release()})"

    return info

def run_task(prompt: str, port: int, model: str):
    start_time = time.perf_counter()

    # Clone the environment to inject OpenAI/MLX routing variables
    env = os.environ.copy()

    # OpenCode natively looks for LOCAL_ENDPOINT for self-hosted models,
    # as well as standard OpenAI variables for routing requests.
    api_base = f"http://127.0.0.1:{port}/v1"
    env["LOCAL_ENDPOINT"] = api_base
    env["OPENAI_API_BASE"] = api_base
    env["OPENAI_API_KEY"] = "mlx"
    env["OPENAI_MODEL"] = model

    try:
        # Pass the prompt directly to OpenCode to trigger non-interactive mode.
        opencode_path = os.path.expanduser("~/.opencode/bin/opencode")
        process = subprocess.run(
            [opencode_path, "run", "--auto", prompt],
            env=env,
            capture_output=True,
            text=True
        )

        if process.returncode != 0:
            console.print(f"\n[bold red]Task Failed (Code {process.returncode}):[/bold red] {process.stderr.strip()}")
            return 0.0
        # If OpenCode returns instantly with no real output, something is wrong with the AI connection
        if len(process.stdout.strip()) < 10:
            console.print(f"\n[bold red]Task Failed (Empty Output):[/bold red] {process.stdout.strip()}")
            return 0.0

    except FileNotFoundError:
        console.print("\n[bold red]Error:[/bold red] 'opencode' CLI not found. Ensure it is installed and in your PATH.")
        exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Task Error:[/bold red] {e}")
        return 0.0

    return time.perf_counter() - start_time

def main():
    parser = argparse.ArgumentParser(description="OpenCode Agent Latency Benchmark")
    parser.add_argument("--env", choices=["host", "vm"], default="vm", help="Execution environment")
    parser.add_argument("--port", type=int, default=8080, help="Port of the AI engine (e.g., 8080 for MLX, 11434 for Ollama)")
    parser.add_argument("--model", type=str, default="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", help="Model name")
    parser.add_argument("--iterations", type=int, default=5, help="Test iterations per task")
    args = parser.parse_args()

    env_info = get_environment_info()
    transport_layer = f"Velo Workspaces AI bridge (vsock port {args.port})" if args.env == "vm" else f"Host Loopback (127.0.0.1:{args.port})"

    env_summary = (
        f"[bold]Platform / Mac Type:[/bold]  [cyan]{env_info['mac_type']}[/cyan]\n"
        f"[bold]CPU Type:[/bold]             [magenta]{env_info['cpu_type']}[/magenta]\n"
        f"[bold]Total RAM:[/bold]            [green]{env_info['total_ram']}[/green]\n"
        f"[bold]Operating System:[/bold]     [blue]{env_info['os_type']}[/blue]\n"
        f"[bold]Transport Layer:[/bold]      [yellow]{transport_layer}[/yellow]\n"
        f"[bold]Agent Framework:[/bold]    [bold white]OpenCode (CLI)[/bold white]\n"
        f"[bold]Target Model:[/bold]       [bold white]{args.model}[/bold white]\n"
        f"[bold]Iterations:[/bold]           {args.iterations} per task"
    )
    console.print(Panel(env_summary, title="[bold cyan]Agentic Latency Test Environment[/bold cyan]", expand=False))
    console.print()

    # We enforce iterative approaches directly in the prompt to avoid
    # Python recursion limits causing the agent to stall on debugging loops.
    tasks = [
        {
            "name": "Math Computation",
            "prompt": "Write a python script to calculate the 1000th Fibonacci number using an iterative loop (do NOT use recursion) and print it. Run it."
        },
        {
            "name": "System Info",
            "prompt": "Write a python script to get the current OS platform, CPU core count, and total RAM in GB. Print them as JSON. Run it."
        },
        {
            "name": "File I/O",
            "prompt": "Write a python script to create a text file containing the numbers 1 to 100, then read it and print the sum. Run it."
        }
    ]

    console.print("[dim]Executing Full Warm-up (Memory Paging, Shaders, KV Prefix Caching)...[/dim]")
    # Run a discardable warmup task to initialize the model into unified memory
    run_task("Write a python script that prints 'Warmup Complete'. Run it.", args.port, args.model)

    final_results = []

    for i, task in enumerate(tasks):
        console.print(f"\n[bold]Running Task {i+1}: {task['name']}[/bold]")
        task_durations = []

        for run in range(args.iterations):
            console.print(f"  ↳ Iteration {run+1}/{args.iterations}...", end=" ")
            duration = run_task(task["prompt"], args.port, args.model)
            task_durations.append(duration)
            console.print(f"{duration:.2f}s")

            # 1-second pause to prevent thermal throttling and allow SQLite DB to close
            time.sleep(1)

        mean = statistics.mean(task_durations)
        stdev = statistics.stdev(task_durations) if args.iterations > 1 else 0
        final_results.append((task["name"], mean, stdev, min(task_durations), max(task_durations)))

    # Final Tabular Output
    table = Table(title=f"OpenCode Agent Turnaround Latency (n={args.iterations})")
    table.add_column("Task", style="cyan")
    table.add_column("Mean (s)", justify="right", style="bold green")
    table.add_column("± Std Dev", justify="right", style="dim")
    table.add_column("Min/Max (s)", justify="right")

    for name, mean, stdev, min_val, max_val in final_results:
        table.add_row(name, f"{mean:.2f}", f"± {stdev:.2f}", f"{min_val:.2f} / {max_val:.2f}")

    console.print("\n")
    console.print(table)

if __name__ == "__main__":
    main()
