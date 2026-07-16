#!/usr/bin/env python3
"""
NXP ICLAD 2026 — SoC Top Stitching Sub-Agent
============================================
Handles Step 4 logic: Compiles top-level SoC wrapper/stitching code 
by evaluating leaf peripheral IP module contracts and structural skeletons.
"""

import argparse
import json
import re
import sys
import os
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

# ─── Constants & Paths ────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


# ─── Heartbeat Monitor ────────────────────────────────────────────────────────
@contextmanager
def heartbeat(message, interval_seconds=15):
    """Log elapsed time every interval_seconds while a block runs."""
    stop_event = threading.Event()

    def run():
        start = time.monotonic()
        while not stop_event.wait(interval_seconds):
            elapsed = int(time.monotonic() - start)
            print(f"[STITCH-AGENT INFO] {message} ({elapsed}s elapsed)", file=sys.stderr, flush=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)


# ─── LLM Direct Connection Client ─────────────────────────────────────────────
def call_model_vertexai(endpoint, prompt, model, max_tokens=16384, max_retries=5, diagnostics_path=None):
    """
    Calls Google's GenAI Endpoint directly using standard urllib,
    bypassing intermediate proxy layers.
    """
    if "gemini" in model.lower():
        model_hard_ceiling = 65536
    else:
        model_hard_ceiling = 8192

    final_max_output_tokens = min(max_tokens, model_hard_ceiling)

    payload_data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": final_max_output_tokens,
            "temperature": 0.2,
            "thinkingConfig": {
                "thinkingBudget": 1024
            }
        }
    }

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[STITCH-AGENT WARN] GEMINI_API_KEY environment variable is not set!", file=sys.stderr, flush=True)

    base_url = endpoint.rstrip("/")
    if ":generateContent" not in base_url:
        url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
    else:
        url = f"{base_url}?key={api_key}" if "?key=" not in base_url else base_url

    body = json.dumps(payload_data).encode("utf-8")
    delay = 2.0
    last_error = None

    for attempt in range(1, max_retries + 1):
        with heartbeat(f"Stitch-Agent API Turn {attempt}/{max_retries}"):
            try:
                req = urllib.request.Request(
                    url, 
                    data=body, 
                    headers={"Content-Type": "application/json"}, 
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=120) as response:
                    resp_data = json.loads(response.read().decode("utf-8"))
                    
                    if diagnostics_path:
                        try:
                            with open(diagnostics_path, "w") as df:
                                json.dump({"status": "SUCCESS", "payload": resp_data}, df, indent=2)
                        except Exception:
                            pass 
                    
                    try:
                        extracted_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                        return extracted_text
                    except (KeyError, IndexError) as extract_err:
                        raise RuntimeError(f"Failed parsing response structure. Raw: {resp_data}") from extract_err

            except urllib.error.HTTPError as e:
                status = e.code
                err_message = e.read().decode("utf-8", errors="ignore")
                last_error = f"HTTP {status}: {err_message}"
                
                if status not in RETRYABLE_HTTP_STATUS:
                    print(f"[STITCH-AGENT FATAL] Non-retryable API status error: {last_error}", file=sys.stderr)
                    break
            except Exception as e:
                last_error = str(e)

        if attempt < max_retries:
            print(f"[STITCH-AGENT WARN] Call choked ({last_error}). Retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)
            delay *= 2.0

    raise RuntimeError(f"Stitch-Agent exhausted all retries. Final error: {last_error}")


# ─── Core Logic Step 4 Execution ──────────────────────────────────────────────
def run_soc_top_stitching(args):
    temp_dir = Path(args.temp_dir)
    output_dir = Path(args.output_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read structural files and prompt assets
    prompt_asset = REPO_ROOT / "prompts" / "soc_top_instruction.txt"
    if not prompt_asset.is_file():
        raise FileNotFoundError(f"Missing core top compilation prompt asset footprint at: {prompt_asset}")

    arch_doc = Path(args.arch_doc_path).read_text(encoding="utf-8") if Path(args.arch_doc_path).is_file() else ""
    tb_skel = Path(args.tb_skel_path).read_text(encoding="utf-8") if Path(args.tb_skel_path).is_file() else ""

    # 2. Re-assemble structural HDL contracts for all generated leaf IP components
    ip_modules_context = ""
    generated_files = [f.strip() for f in args.generated_files.split(",") if f.strip()] if args.generated_files else []

    for f in generated_files:
        fpath = Path(f) if Path(f).is_absolute() else output_dir / f
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            mod_match = re.search(r'(\bmodule\s+\w+.*?;\s*)', content, re.DOTALL)
            ticks = '`' * 3
            ip_modules_context += f"\n### Contract ({fpath.name}):\n{ticks}verilog\n{mod_match.group(1) if mod_match else content[:500]}\n{ticks}\n"

    # 3. Format dynamic compile payload prompt
    instruction_base = prompt_asset.read_text(encoding="utf-8")
    prompt = instruction_base.format(
        problem=args.problem.upper(),
        arch_doc=arch_doc[:6000],
        ip_modules_context=ip_modules_context,
        tb_skel=tb_skel[:4000]
    )

    # 4. Invoke LLM interface
    print(f"[STITCH-AGENT] Contacting Vertex AI to synthesize SoC Stitch Top wrapper...", file=sys.stderr)
    diagnostics_path = temp_dir / "soc_top_diagnostics.json"
    response = call_model_vertexai(
        args.model_endpoint, 
        prompt, 
        args.model, 
        max_tokens=8192, 
        diagnostics_path=diagnostics_path
    )
    
    # 5. Save responses and generate output manifest block
    soc_response_path = temp_dir / "soc_response.txt"
    soc_response_path.write_text(response, encoding="utf-8")

    manifest_data = {
        "soc_response": response,
        "response_file_path": str(soc_response_path)
    }

    manifest_out_path = Path(args.manifest_out)
    manifest_out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_out_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    
    print(f"[STITCH-AGENT] Process finished. Manifest written to: {manifest_out_path}", file=sys.stderr)


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sub-Agent tasking SoC Top level connection assembly")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-endpoint", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--arch-doc-path", required=True)
    parser.add_argument("--tb-skel-path", required=True)
    parser.add_argument("--generated-files", required=True, help="Comma-separated list of compiled module RTL paths")
    parser.add_argument("--manifest-out", required=True)

    args = parser.parse_args()
    try:
        run_soc_top_stitching(args)
        sys.exit(0)
    except Exception as e:
        print(f"[STITCH-AGENT ERROR] Execution failed: {e}", file=sys.stderr)
        sys.exit(1)
