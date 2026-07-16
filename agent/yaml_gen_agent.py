#!/usr/bin/env python3
"""
NXP ICLAD 2026 — YAML Generation Sub-Agent
==========================================
Handles Step 2 logic: Infers IP YAML specifications based on architectural documents
and top-level testbench skeletons, filtering out the top module.
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

# Load the dynamic system tracking parameters map
IP_CONFIG_JSON = REPO_ROOT / "config" / "supported_ip_types.json"
if not IP_CONFIG_JSON.is_file():
    raise FileNotFoundError(f"CRITICAL: System tracking map asset missing at: {IP_CONFIG_JSON}")
SUPPORTED_IP_TYPE_PARAMETERS = json.loads(IP_CONFIG_JSON.read_text(encoding="utf-8"))


# ─── Heartbeat Monitor ────────────────────────────────────────────────────────
@contextmanager
def heartbeat(message, interval_seconds=15):
    """Log elapsed time every interval_seconds while a block runs."""
    stop_event = threading.Event()

    def run():
        start = time.monotonic()
        while not stop_event.wait(interval_seconds):
            elapsed = int(time.monotonic() - start)
            print(f"[SUB-AGENT INFO] {message} ({elapsed}s elapsed)", file=sys.stderr, flush=True)

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
        print("[SUB-AGENT WARN] GEMINI_API_KEY environment variable is not set!", file=sys.stderr, flush=True)

    base_url = endpoint.rstrip("/")
    if ":generateContent" not in base_url:
        url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
    else:
        url = f"{base_url}?key={api_key}" if "?key=" not in base_url else base_url

    body = json.dumps(payload_data).encode("utf-8")
    delay = 2.0
    last_error = None

    for attempt in range(1, max_retries + 1):
        with heartbeat(f"Sub-Agent API Turn {attempt}/{max_retries}"):
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
                    print(f"[SUB-AGENT FATAL] Non-retryable API status error: {last_error}", file=sys.stderr)
                    break
            except Exception as e:
                last_error = str(e)

        if attempt < max_retries:
            print(f"[SUB-AGENT WARN] Call choked ({last_error}). Retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)
            delay *= 2.0

    raise RuntimeError(f"Sub-Agent exhausted all retries. Final error: {last_error}")


def extract_yaml_blocks(text):
    # Safe regex avoiding literal backticks to prevent editor parsing bugs
    pattern = r'`{3}(?:yaml|yml)?\s*\n(.*?)`{3}'
    return re.findall(pattern, text, re.DOTALL | re.IGNORECASE)


# ─── Core Logic Step 2 Execution ──────────────────────────────────────────────
def run_yaml_inference(args):
    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read the input files provided by the orchestrator
    arch_doc = Path(args.arch_doc_path).read_text(encoding="utf-8")
    tb_skel = Path(args.tb_skel_path).read_text(encoding="utf-8")
    parsing_instr = Path(args.instr_path).read_text(encoding="utf-8")

    prompt_asset = REPO_ROOT / "prompts" / "yaml_inference_instruction.txt"
    if not prompt_asset.is_file():
        raise FileNotFoundError(f"Missing core prompt text asset footprint at: {prompt_asset}")

    # 2. Extract unique module stems
    arch_stems = []
    for f in re.findall(r'<code>\s*([^<]+\.v)\s*</code>', arch_doc):
        stem_name = Path(f).stem
        if stem_name not in arch_stems:
            arch_stems.append(stem_name)

    # 3. Identify Top module
    top_module_name = ""
    for stem in arch_stems:
        # Using '\x28' (hex code for ASCII '(') inside regex pattern
        # to prevent bracket-matching warnings in rigid code editors.
        if re.search(r'\b' + re.escape(stem) + r'\s+\w+\s*\x28', tb_skel):
            top_module_name = stem
            break

    seen_ips = [stem for stem in arch_stems if stem != top_module_name]

    manifest_prompt_str = "".join([
        f"- For ip_type `{b}`: Mandated configuration fields: {k}\n" 
        for b, k in SUPPORTED_IP_TYPE_PARAMETERS.items() if b in seen_ips or b == "apb_fabric"
    ])

    # 4. Read externalized prompt and compile
    instruction_base = prompt_asset.read_text(encoding="utf-8")
    prompt = instruction_base.format(
        problem=args.problem.upper(),
        parsing_instr=parsing_instr,
        target_ips_str=", ".join(seen_ips),
        manifest_prompt_str=manifest_prompt_str,
        arch_doc=arch_doc,
        tb_skel_prefix=tb_skel[:3000],
        valid_core_tokens=list(SUPPORTED_IP_TYPE_PARAMETERS.keys())
    )

    if top_module_name:
        dynamic_rule = f"""

================================================================================
STRICT RUNTIME ARCHITECTURAL PIPELINE RULE:
- For this specific problem instance, the structural top-level SoC wrapper/integration module name is dynamically determined to be: '{top_module_name}'
- Do NOT search for or validate '{top_module_name}' against your 'valid_core_tokens' or 'ip_type' registry lists.
- This block {top_module_name} need not have an 'ip_type'.
================================================================================
"""
        prompt += dynamic_rule

    # 5. Call LLM
    print(f"[SUB-AGENT] Contacting Vertex AI API for YAML mapping...", file=sys.stderr)
    diagnostics_path = temp_dir / "yaml_inference_diagnostics.json"
    response = call_model_vertexai(args.model_endpoint, prompt, args.model, diagnostics_path=diagnostics_path)
    (temp_dir / "yaml_response.txt").write_text(response, encoding="utf-8")

    # 6. Parse and filter results
    yaml_blocks = extract_yaml_blocks(response)
    ip_yaml_blocks = []
    saved_paths = []

    for i, yaml_str in enumerate(yaml_blocks):
        name_match = re.search(r'name:\s*(\w+)', yaml_str)
        ip_type_match = re.search(r'ip_type:\s*(\w+)', yaml_str)
        
        block_name = name_match.group(1) if name_match else ""
        block_ip_type = ip_type_match.group(1) if ip_type_match else ""
        
        if block_name == top_module_name or block_ip_type == top_module_name:
            print(f"[SUB-AGENT INFO] Skipping YAML generation for top module: '{top_module_name}'", file=sys.stderr)
            continue
            
        individual_name = block_name if block_name else f'spec_{i}'
        individual_path = temp_dir / f"{individual_name}.yaml"
        individual_path.write_text(yaml_str, encoding="utf-8")
        
        ip_yaml_blocks.append(yaml_str)
        saved_paths.append(str(individual_path))

    # 7. Write Manifest containing data for the Orchestrator
    manifest_data = {
        "yaml_blocks": ip_yaml_blocks,
        "saved_yaml_files": saved_paths,
        "top_module_name": top_module_name
    }
    
    manifest_out_path = Path(args.manifest_out)
    manifest_out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_out_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    print(f"[SUB-AGENT] Process finished. Manifest written to: {manifest_out_path}", file=sys.stderr)


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sub-Agent tasking YAML compilation specs")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-endpoint", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--arch-doc-path", required=True)
    parser.add_argument("--tb-skel-path", required=True)
    parser.add_argument("--instr-path", required=True)
    parser.add_argument("--manifest-out", required=True)
    
    args = parser.parse_args()
    try:
        run_yaml_inference(args)
        sys.exit(0)
    except Exception as e:
        print(f"[SUB-AGENT ERROR] Execution failed: {e}", file=sys.stderr)
        sys.exit(1)
