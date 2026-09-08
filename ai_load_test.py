import asyncio
import time
import httpx
import argparse
import platform
import subprocess
import os

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

    else:
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

async def worker(client: httpx.AsyncClient, client_id: int, endpoint: str, model: str):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Write a 50-word poem on computing."}],
        "stream": False,
        "temperature": 0.5
    }
    start = time.perf_counter()
    try:
        # Utilizing the shared persistent connection pool
        resp = await client.post(endpoint, json=payload)
        elapsed = time.perf_counter() - start
        if resp.status_code == 200:
            print(f"  [Client {client_id:02d}] Finished in {elapsed:5.2f}s (HTTP 200)")
            return True, elapsed
        else:
            print(f"  [Client {client_id:02d}] Failed with HTTP {resp.status_code}")
            return False, elapsed
    except Exception as e:
        print(f"  [Client {client_id:02d}] Connection Error: {e}")
        return False, 0.0

async def main():
    parser = argparse.ArgumentParser(description="AI Bridge Load Test (Keep-Alive Optimized)")
    parser.add_argument("--env", choices=["host", "vm"], default="vm", help="Execution environment")
    parser.add_argument("--port", type=int, default=11434, help="Port of the AI engine")
    parser.add_argument("--model", type=str, default="qwen2.5-coder:7b", help="Model name")
    parser.add_argument("--clients", type=int, default=8, help="Number of concurrent clients")
    args = parser.parse_args()

    endpoint = f"http://127.0.0.1:{args.port}/v1/chat/completions"
    env_info = get_environment_info()
    transport_layer = "Velo vsock Proxy" if args.env == "vm" else "Native macOS Loopback"

    print("=" * 60)
    print("           AI BRIDGE CONCURRENCY LOAD TEST")
    print("=" * 60)
    print(f"  Mac Type:       {env_info['mac_type']}")
    print(f"  CPU Type:       {env_info['cpu_type']}")
    print(f"  Total Cores:    {env_info['total_cores']}")
    print(f"  Total RAM:      {env_info['total_ram']}")
    print(f"  Operating Sys:  {env_info['os_type']}")
    print(f"  Target URL:     {endpoint}")
    print(f"  Transport:      {transport_layer}")
    print(f"  Model:          {args.model}")
    print(f"  Concurrency:    {args.clients} Parallel Clients")
    print("-" * 60)
    print(f"Launching {args.clients} parallel requests...")

    start_total = time.perf_counter()

    # Configure connection pool limits to match the requested concurrency
    limits = httpx.Limits(max_keepalive_connections=args.clients, max_connections=args.clients)

    # Initialize a single shared AsyncClient for all workers
    async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
        tasks = [worker(client, i + 1, endpoint, args.model) for i in range(args.clients)]
        results = await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_total

    successes = sum(1 for success, _ in results if success)
    durations = [d for success, d in results if success]
    avg_req_time = sum(durations) / len(durations) if durations else 0.0

    print("-" * 60)
    print(f"  Status:          {successes}/{args.clients} Requests Successful")
    print(f"  Total Wall Time: {total_time:.2f}s")
    print(f"  Avg Client Time: {avg_req_time:.2f}s")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
