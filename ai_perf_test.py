import time
import json
import httpx
import argparse
import platform
import subprocess
import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

def get_environment_info() -> dict:
    """Extracts system hardware specifications across macOS Host and Linux/Guest VMs."""
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

def run_single_test(client: httpx.Client, test_id: int, endpoint: str, model: str, prompt: str):
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "temperature": 0.0, # 0.0 forces deterministic generation for accurate comparisons
        "options": {
            "num_ctx": 4096 # Locks KV cache memory allocation
        }
    }

    start_time = time.perf_counter()
    first_token_time = None
    token_count = 0

    # Uses the persistent connection pool from the provided client
    with client.stream("POST", endpoint, json=payload, headers=headers) as response:
        if response.status_code != 200:
            console.print(f"[bold red]Error: HTTP {response.status_code}[/bold red]")
            return None

        for chunk in response.iter_lines():
            if not chunk or chunk.startswith(":"):
                continue
            if chunk.startswith("data: "):
                data_str = chunk[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0]["delta"].get("content", "")
                    if delta:
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                        token_count += 1
                except json.JSONDecodeError:
                    continue

    end_time = time.perf_counter()

    ttft = (first_token_time - start_time) * 1000 if first_token_time else 0
    total_time = end_time - start_time
    generation_time = end_time - first_token_time if first_token_time else total_time
    tps = token_count / generation_time if generation_time > 0 else 0

    return {
        "test_id": test_id,
        "ttft_ms": ttft,
        "total_time_s": total_time,
        "token_count": token_count,
        "tps": tps
    }

def main():
    parser = argparse.ArgumentParser(description="AI Bridge Performance Benchmark (Keep-Alive Optimized)")
    parser.add_argument("--env", choices=["host", "vm"], default="vm", help="Execution environment")
    parser.add_argument("--port", type=int, default=11434, help="Port of the AI engine")
    parser.add_argument("--model", type=str, default="qwen2.5-coder:7b", help="Model name to test")
    parser.add_argument("--iterations", type=int, default=5, help="Number of benchmark iterations")
    args = parser.parse_args()

    endpoint = f"http://127.0.0.1:{args.port}/v1/chat/completions"
    env_info = get_environment_info()
    prompt = "Write a comprehensive 400-word explanation of how virtual memory paging works in modern operating systems."

    transport_layer = "[bold yellow]Velo vsock Proxy[/bold yellow]" if args.env == "vm" else "[bold green]Native macOS Loopback[/bold green]"

    env_summary = (
        f"[bold]Platform / Mac Type:[/bold]  [cyan]{env_info['mac_type']}[/cyan]\n"
        f"[bold]CPU Type:[/bold]             [magenta]{env_info['cpu_type']}[/magenta]\n"
        f"[bold]CPU Cores:[/bold]            [yellow]{env_info['total_cores']}[/yellow]\n"
        f"[bold]Total RAM:[/bold]            [green]{env_info['total_ram']}[/green]\n"
        f"[bold]Operating System:[/bold]     [blue]{env_info['os_type']}[/blue]\n"
        f"[bold]Transport Layer:[/bold]      {transport_layer}\n"
        f"[bold]Model:[/bold]                [bold white]{args.model}[/bold white]"
    )
    console.print(Panel(env_summary, title="[bold cyan]AI Bridge Test Environment[/bold cyan]", expand=False))
    console.print()

    results = []

    # Initialize a single client with HTTP/1.1 persistent connections enabled
    limits = httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0)
    with httpx.Client(timeout=60.0, limits=limits) as client:

        console.print("[dim]Executing warm-up run (TCP socket init, vsock handshake, model caching)...[/dim]")
        _ = run_single_test(client, 0, endpoint, args.model, prompt)

        for i in range(1, args.iterations + 1):
            console.print(f"Running iteration {i}/{args.iterations}...")
            res = run_single_test(client, i, endpoint, args.model, prompt)
            if res:
                results.append(res)
            time.sleep(1)

    table = Table(title=f"AI Benchmark Results — {env_info['mac_type']} ({env_info['cpu_type']})")
    table.add_column("Run #", justify="center")
    table.add_column("TTFT (ms)", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Gen Time (s)", justify="right")
    table.add_column("Speed (tok/s)", justify="right", style="bold green")

    for r in results:
        table.add_row(
            str(r["test_id"]),
            f"{r['ttft_ms']:.2f}",
            str(r["token_count"]),
            f"{r['total_time_s']:.2f}",
            f"{r['tps']:.2f}"
        )

    avg_ttft = sum(r["ttft_ms"] for r in results) / len(results) if results else 0
    avg_tps = sum(r["tps"] for r in results) / len(results) if results else 0

    console.print()
    console.print(table)
    console.print(f"[bold]Average TTFT:[/bold]       {avg_ttft:.2f} ms")
    console.print(f"[bold]Average Throughput:[/bold] [bold green]{avg_tps:.2f} tokens/sec[/bold green]\n")

if __name__ == "__main__":
    main()
