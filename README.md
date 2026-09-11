# veloworkspace-tools

Benchmark scripts used to measure [Velo Workspaces](https://www.veloworkspaces.com)' AI Bridge — comparing local LLM inference reached from the macOS host directly vs. reached from inside a Linux VM over AI Bridge's vsock-based channel.

Full writeup with methodology and results: *(dev.to link once published)*

## What's here

- **`ai_perf_test.py`** — single-request benchmark. Measures time-to-first-token and sustained throughput (tok/s) over 5 iterations, streaming, deterministic (`temperature=0`).
- **`ai_load_test.py`** — concurrency benchmark. Fires N parallel requests (default 8) at the same endpoint and reports total wall time and average per-client latency.
- **`oi_perf_test.py`** — real-world agentic-loop benchmark using [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter). Measures the full round trip: prompt → generated code → code execution → result, across three representative tasks (math computation, system info, file I/O), 5 iterations each.
- **`opencode_perf_test.py`** — the same agentic-loop benchmark as `oi_perf_test.py`, driving [OpenCode](https://github.com/sst/opencode) (`opencode run --auto`) instead of Open Interpreter. Same three tasks, same 5-iteration protocol; use whichever agent CLI matches what you're actually shipping.

All four auto-detect whether they're running on macOS (host) or Linux (VM) and print hardware/OS info alongside the results, so output is self-describing.

## Requirements

```
pip install httpx rich open-interpreter
```

`oi_perf_test.py` additionally requires [Ollama](https://ollama.com) running locally (or reachable at the configured `--port`) with the target model pulled.

`opencode_perf_test.py` additionally requires the [OpenCode CLI](https://github.com/sst/opencode) installed at `~/.opencode/bin/opencode`, and an OpenAI-compatible server (Ollama, MLX, llama-server, …) reachable at `--port`.

## Usage

Run on the host (against Ollama's native loopback) and again from inside a Velo Workspaces VM (against AI Bridge), then compare:

```bash
# Single-request speed
python ai_perf_test.py --env host --model qwen2.5-coder:7b
python ai_perf_test.py --env vm   --model qwen2.5-coder:7b

# Concurrent load (8 clients by default)
python ai_load_test.py --env host --model qwen2.5-coder:7b --clients 8
python ai_load_test.py --env vm   --model qwen2.5-coder:7b --clients 8

# Real agentic-loop latency (Open Interpreter)
python oi_perf_test.py --env host
python oi_perf_test.py --env vm

# Real agentic-loop latency (OpenCode)
python opencode_perf_test.py --env host --port 8080 --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
python opencode_perf_test.py --env vm   --port 8080 --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

`--env` only affects the printed environment banner (host vs. VM auto-detected hardware info) — point `--port` at whichever endpoint you're actually testing (Ollama's native port on the host, or the AI Bridge-forwarded port inside a workspace).

## ⚠️ Before every run: stop all VMs and restart Ollama fresh

This matters more than it sounds like it should. Between the **host** run and the **VM** run of any of these scripts, fully stop any running Velo Workspaces VM and restart `ollama serve` from scratch before starting the next test. A workspace or model server left running in the background from a previous run contends with the one you're actually measuring for CPU and scheduling, and it shows up in the numbers — in our own testing, skipping this step produced wildly bimodal, unrepresentative results on `oi_perf_test.py` (some iterations 10x slower than others, purely from leftover contention) that vanished entirely once we adopted a strict stop-everything-then-restart-fresh protocol between every run. Sequence per test:

```
stop all VMs → stop Ollama → ollama serve → run the host test
stop all VMs → stop Ollama → ollama serve → start the VM → ssh in → run the vm test
```

## Sample results

Mac mini (Apple M4, 10-core, 16GB), Linux VM (Ubuntu Server 26.04 minimized, 4 vCPU, 4GB), `qwen2.5-coder:7b` (Q4_K_M) served by Ollama on the host. Measured with the stop-everything-then-restart protocol above.

| Test | Host | AI Bridge (VM) | Delta |
|---|---|---|---|
| Time to first token | 56 ms | 59 ms | +6% |
| Throughput | 22.09 tok/s | 21.78 tok/s | −1% |
| Concurrent load (8 clients, wall time) | 15.04 s | 12.73 s | 15% faster via AI Bridge |
| Agentic loop, mean per task (Open Interpreter) | 6.45–9.08 s | 5.38–6.56 s | 17–28% faster via AI Bridge |

Raw single-request speed is close to a wash — AI Bridge adds one network hop, which shows up as a small, expected overhead. Concurrent load and real agentic workflows both came out faster through AI Bridge, most likely because the VM's client process runs isolated from whatever else is happening on the host, rather than sharing the same physical cores as the process it's talking to.

## Methodology notes

- All three scripts target an OpenAI-compatible `/v1/chat/completions` endpoint (Ollama's).
- `ai_perf_test.py` and `ai_load_test.py` measure the model server directly. `oi_perf_test.py` measures a full agentic tool-use loop, so its numbers include code generation, process spawning, execution, and output parsing — not just inference.
- Results are hardware-, model-, and workload-specific. Re-run on your own setup before drawing conclusions for a different model or Mac.

## License

MIT — see [LICENSE](LICENSE).
