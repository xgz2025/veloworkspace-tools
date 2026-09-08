import time
import argparse
import platform
import subprocess
import os
import statistics
from interpreter import interpreter
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

def run_task(task_name: str, prompt: str):
    start_time = time.perf_counter()

    try:
        interpreter.chat(prompt, display=False)
    except Exception as e:
        console.print(f"[bold red]Task Failed:[/bold red] {e}")
        return 0.0

    return time.perf_counter() - start_time

def main():
    parser = argparse.ArgumentParser(description="Open Interpreter Latency Benchmark")
    parser.add_argument("--env", choices=["host", "vm"], default="vm", help="Execution environment")
    parser.add_argument("--iterations", type=int, default=5, help="Test iterations per task")
    args = parser.parse_args()

    # Optimized settings for 16GB Mac
    interpreter.auto_run = True
    interpreter.llm.model = "ollama/qwen2.5-coder:7b"
    interpreter.llm.api_base = "http://127.0.0.1:11434"
    interpreter.llm.context_window = 4096
    interpreter.llm.max_tokens = 512
    interpreter.custom_instructions = "Output strictly the code required. No conversational filler."

    env_info = get_environment_info()
    transport_layer = "Velo Workspaces AI bridge (vsock)" if args.env == "vm" else "Host Loopback (127.0.0.1)"

    env_summary = (
        f"[bold]Platform / Mac Type:[/bold]  [cyan]{env_info['mac_type']}[/cyan]\n"
        f"[bold]CPU Type:[/bold]             [magenta]{env_info['cpu_type']}[/magenta]\n"
        f"[bold]Total RAM:[/bold]            [green]{env_info['total_ram']}[/green]\n"
        f"[bold]Operating System:[/bold]     [blue]{env_info['os_type']}[/blue]\n"
        f"[bold]Transport Layer:[/bold]      [yellow]{transport_layer}[/yellow]\n"
        f"[bold]Model:[/bold]                [bold white]{interpreter.llm.model}[/bold white]\n"
        f"[bold]Iterations:[/bold]           {args.iterations} per task"
    )
    console.print(Panel(env_summary, title="[bold cyan]Agentic Latency Test Environment[/bold cyan]", expand=False))
    console.print()

    # Real-world benchmark tasks requiring code generation AND execution
    tasks = [
        {
            "name": "Math Computation",
            "prompt": "Write a python script to calculate the 1000th Fibonacci number and print it. Run it."
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

    console.print("[dim]Executing Full Warm-up (Memory Paging, Metal Shaders, REPL init)...[/dim]")
    run_task("Warm-up", "Write a python script that prints 'Warmup Complete'. Run it.")
    interpreter.messages = []

    final_results = []

    for i, task in enumerate(tasks):
        console.print(f"\n[bold]Running Task {i+1}: {task['name']}[/bold]")
        task_durations = []

        for run in range(args.iterations):
            console.print(f"  ↳ Iteration {run+1}/{args.iterations}...", end=" ")
            duration = run_task(task["name"], task["prompt"])
            task_durations.append(duration)
            console.print(f"{duration:.2f}s")

            interpreter.messages = [] # Clear context between runs to prevent token bloat
            time.sleep(1) # Thermal cool-down

        mean = statistics.mean(task_durations)
        stdev = statistics.stdev(task_durations) if args.iterations > 1 else 0
        final_results.append((task["name"], mean, stdev, min(task_durations), max(task_durations)))

    # Print Final Summary Table
    table = Table(title=f"Open Interpreter Turnaround Latency (n={args.iterations})")
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
