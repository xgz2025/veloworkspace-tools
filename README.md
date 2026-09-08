# veloworkspace-tools

Benchmark scripts used to measure [Velo Workspaces](https://apps.apple.com/app/velo-workspaces/id6805509975)' AI Bridge — comparing local LLM inference reached from the macOS host directly vs. reached from inside a Linux VM over AI Bridge's vsock-based channel.

Full writeup with methodology and results: *(dev.to link once published)*

## What's here

- **`ai_perf_test.py`** — single-request benchmark. Measures time-to-first-token and sustained throughput (tok/s) over 5 iterations, streaming, deterministic (`temperature=0`).
- **`ai_load_test.py`** — concurrency benchmark. Fires N parallel requests (default 8) at the same endpoint and reports total wall time and average per-client latency.
- **`oi_perf_test.py`** — real-world agentic-loop benchmark using [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter). Measures the full round trip: prompt → generated code → code execution → result, across three representative tasks (math computation, system info, file I/O), 5 iterations each.

All three auto-detect whether they're running on macOS (host) or Linux (VM) and print hardware/OS info alongside the results, so output is self-describing.

## Requirements

```
pip install httpx rich open-interpreter
```

`oi_perf_test.py` additionally requires [Ollama](https://ollama.com) running locally (or reachable at the configured `--port`) with the target model pulled.

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
```

`--env` only affects the printed environment banner (host vs. VM auto-detected hardware info) — point `--port` at whichever endpoint you're actually testing (Ollama's native port on the host, or the AI Bridge-forwarded port inside a workspace).

## Methodology notes

- All three scripts target an OpenAI-compatible `/v1/chat/completions` endpoint (Ollama's).
- `ai_perf_test.py` and `ai_load_test.py` measure the model server directly. `oi_perf_test.py` measures a full agentic tool-use loop, so its numbers include code generation, process spawning, execution, and output parsing — not just inference.
- Results are hardware-, model-, and workload-specific. Re-run on your own setup before drawing conclusions for a different model or Mac.

## License

MIT — see [LICENSE](LICENSE).
