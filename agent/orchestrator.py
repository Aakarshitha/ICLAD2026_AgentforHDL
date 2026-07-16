#!/usr/bin/env python3
"""
NXP ICLAD 2026 — Verification-Aware Orchestrator Script
======================================================
Manages high-level program execution, delegating specialized sub-tasks 
such as YAML schema inference and SoC stitching to modular sub-agents.
Passes skills STRICTLY to the testbench generation sub-agent to prevent bloating.
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import os
import urllib.request
import urllib.error
import yaml

# ─── Constants & Paths ────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}

# Ensure REPO_ROOT is in sys.path to cleanly import local configurations
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Attempt to load the structural strategy configuration
try:
    from config.strategy_tips import STRATEGY_TIPS
except ImportError:
    print("[ORCHESTRATOR WARN] Failed to load config/strategy_tips.py. Using empty baseline default.", file=sys.stderr)
    STRATEGY_TIPS = {"easy": {}, "medium": {}, "hard": {}}


# ─── Heartbeat Monitor ────────────────────────────────────────────────────────
@contextmanager
def heartbeat(message, interval_seconds=15):
    """Log elapsed time every interval_seconds while a block runs."""
    stop_event = threading.Event()

    def run():
        start = time.monotonic()
        while not stop_event.wait(interval_seconds):
            elapsed = int(time.monotonic() - start)
            print(f"[ORCHESTRATOR INFO] {message} ({elapsed}s elapsed)", file=sys.stderr, flush=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)


# ─── Helper Extraction and Compilation Functions ──────────────────────────────
def extract_verilog_blocks(text):
    results = []
    chunks = re.split(r'`{3}(?:verilog|v|sv|systemverilog)?\s*\n', text, flags=re.IGNORECASE)
    for chunk in chunks[1:]:
        end = chunk.find('`' * 3)
        code = (chunk[:end] if end >= 0 else chunk).strip()
        if not code or 'module' not in code:
            continue
        fname_match = re.search(r'//\s*FILE:\s*(\S+\.v)', code)
        if fname_match:
            fname = fname_match.group(1)
        else:
            mod_match = re.search(r'module\s+(\w+)', code)
            fname = (mod_match.group(1) + ".v") if mod_match else f"module_{len(results)}.v"
        results.append((fname, code))
    return results


def rtl_gen_from_yaml(yaml_content, rtl_gen_lib, output_dir, temp_dir, idx=0):
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        spec_dict = yaml.safe_load(yaml_content)
    except Exception as e:
        print(f"[ORCHESTRATOR WARN] Failed to parse YAML: {e}", file=sys.stderr)
        spec_dict = {}

    if isinstance(spec_dict, dict) and "parameters" in spec_dict:
        params = spec_dict.get("parameters", {})
        if isinstance(params, dict):
            for key, val in params.items():
                if key not in spec_dict:
                    spec_dict[key] = val

    try:
        clean_yaml_content = yaml.dump(spec_dict, default_flow_style=False)
    except Exception as e:
        clean_yaml_content = yaml_content

    yaml_path = temp_dir / "spec_temp.yaml"
    yaml_path.write_text(clean_yaml_content, encoding="utf-8")

    gen_script = Path(rtl_gen_lib) / "rtl_gen_main.py"
    if not gen_script.is_file():
        print(f"[ORCHESTRATOR WARN] rtl_gen_main.py not found at: {gen_script}", file=sys.stderr)
        return []

    result = subprocess.run(
        [sys.executable, str(gen_script), "--spec", str(yaml_path), "--outdir", str(output_dir)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"[ORCHESTRATOR WARN] RTL gen failed for spec_{idx:02d}:\n{result.stderr[:400]}", file=sys.stderr)
        return []

    generated = []
    for l in result.stdout.splitlines():
        if l.startswith("[GEN]"):
            path_part = l.split("->")[1].strip().split()[0] if "->" in l else l.replace("[GEN]", "").strip().split()[0]
            generated.append(path_part)
            
    return generated


def extract_ports_from_verilog(verilog_content):
    clean_content = re.sub(r'//.*', '', verilog_content)
    clean_content = re.sub(r'/\*.*?\*/', '', clean_content, flags=re.DOTALL)
    module_header_match = re.search(r'\bmodule\s+\w+(?:\s*#\s*\(.*?\))?\s*\((.*?)\)\s*;', clean_content, re.DOTALL)
    if not module_header_match:
        return []
    
    port_block = module_header_match.group(1)
    raw_ports = port_block.split(',')
    parsed_ports = []
    current_dir, current_size = None, ""
    
    for raw_port in raw_ports:
        token = raw_port.strip()
        if not token: continue
        dir_match = re.search(r'\b(input|output)\b', token)
        if dir_match:
            current_dir = dir_match.group(1)
            current_size = "" 
        size_match = re.search(r'(\[[^\]]+\])', token)
        if size_match:
            current_size = size_match.group(1)
        elif dir_match and not size_match:
            current_size = ""
            
        name_match = re.search(r'(\b\w+\b)\s*$', token)
        if name_match and current_dir:
            port_name = name_match.group(1)
            if port_name not in ['input', 'output', 'wire', 'reg', 'logic']:
                parsed_ports.append((current_dir, current_size, port_name))
    return parsed_ports


def generate_single_tb(dut_name, instance_num, parsed_ports):
    template_path = REPO_ROOT / "templates" / "single_tb_template.v"
    if not template_path.is_file():
        raise FileNotFoundError(f"Missing verification platform template blueprint at: {template_path}")
        
    inputs = [p for p in parsed_ports if p[0] == "input"]
    outputs = [p for p in parsed_ports if p[0] == "output"]
    
    clk_ports = [p[2] for p in inputs if p[2] in ["clk", "pclk", "sys_clk"]]
    rst_ports = [p[2] for p in inputs if p[2] in ["rst_n", "presetn", "sys_rst_n"]]
    primary_clk = clk_ports[0] if clk_ports else None
    primary_rst = rst_ports[0] if rst_ports else None

    sig_decls = [f"    reg {s[1]} {s[2]};" if s[1] else f"    reg {s[2]};" for s in inputs] + \
                [f"    wire {s[1]} {s[2]};" if s[1] else f"    wire {s[2]};" for s in outputs]
                
    clk_gen = f"    always #(CLK_PERIOD/2) {primary_clk} = ~{primary_clk};" if primary_clk else "    // No active clock structure detected."
    mappings = ",\n".join([f"        .{p[2]:<14} ({p[2]})" for p in parsed_ports])
    
    inits = []
    for _, _, name in inputs:
        inits.append(f"        {name:<13} = 0;" if name != primary_rst else f"        {name:<13} = 0; // Assert Active-Low Reset")
        
    rst_seq = f"        {primary_rst:<13} = 1; // De-assert Active-Low Reset" if primary_rst else "        //"

    template_text = template_path.read_text(encoding="utf-8")
    return template_text.format(
        tb_module_name=f"tb_{dut_name}_{instance_num}",
        signal_declarations="\n".join(sig_decls),
        clock_generation=clk_gen,
        dut_name=dut_name,
        uut_instance_name=f"uut_{dut_name}_{instance_num}",
        port_mappings=mappings,
        signal_initializations="\n".join(inits),
        reset_toggle=rst_seq
    )


# ─── Metrics Capturing & Compilation Function ─────────────────────────────────
def collect_and_save_metrics(info, durations):
    """
    Parses diagnostics outputs from sub-agents to extract Google API token limits,
    measures total duration metrics, displays a formatted summary log,
    and exports a comprehensive JSON metrics summary.
    """
    temp_dir = Path(info["temp_dir"])
    output_dir = Path(info["output_dir"])

    metrics = {
        "execution_durations_seconds": durations,
        "token_usage": {},
        "aggregated_totals": {
            "total_prompt_tokens": 0,
            "total_output_tokens": 0,
            "total_overall_tokens": 0
        },
        "file_statistics": {
            "yaml_specs_generated": 0,
            "verilog_rtl_files_saved": 0
        }
    }

    diagnostic_files = {
        "yaml_gen_agent": temp_dir / "yaml_inference_diagnostics.json",
        "top_stitch_agent": temp_dir / "soc_top_diagnostics.json",
        "tb_gen_agent": temp_dir / "tb_gen_diagnostics.json"
    }

    total_prompt = 0
    total_candidates = 0
    total_overall = 0

    print("\n" + "=" * 65, file=sys.stderr)
    print("           NXP ICLAD 2026 — PERFORMANCE METRICS REPORT", file=sys.stderr)
    print("=" * 65, file=sys.stderr)

    for agent_name, path in diagnostic_files.items():
        agent_metrics = {
            "prompt_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "api_call_status": "UNKNOWN"
        }

        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                agent_metrics["api_call_status"] = data.get("status", "SUCCESS")
                
                payload = data.get("payload", {})
                usage = payload.get("usageMetadata", {})
                
                p_tokens = usage.get("promptTokenCount", 0)
                o_tokens = usage.get("candidatesTokenCount", 0)
                t_tokens = usage.get("totalTokenCount", 0)

                agent_metrics["prompt_tokens"] = p_tokens
                agent_metrics["output_tokens"] = o_tokens
                agent_metrics["total_tokens"] = t_tokens

                total_prompt += p_tokens
                total_candidates += o_tokens
                total_overall += t_tokens

            except Exception as e:
                print(f"[METRICS WARN] Failed parsing token metrics for {agent_name}: {e}", file=sys.stderr)
        else:
            agent_metrics["api_call_status"] = "DIAGNOSTIC_FILE_MISSING"

        metrics["token_usage"][agent_name] = agent_metrics

        print(f"\n[{agent_name.upper()}]", file=sys.stderr)
        print(f"  - Execution Status: {agent_metrics['api_call_status']}", file=sys.stderr)
        print(f"  - Input Prompt:     {agent_metrics['prompt_tokens']:} tokens", file=sys.stderr)
        print(f"  - Output Generation: {agent_metrics['output_tokens']:} tokens", file=sys.stderr)
        print(f"  - Total API Cost:    {agent_metrics['total_tokens']:} tokens", file=sys.stderr)
        if agent_name in durations:
            print(f"  - Compute Time:     {durations[agent_name]:.2f}s", file=sys.stderr)

    yaml_count = len(list(temp_dir.glob("*.yaml")))
    verilog_count = len(list(output_dir.glob("*.v")))

    metrics["aggregated_totals"]["total_prompt_tokens"] = total_prompt
    metrics["aggregated_totals"]["total_output_tokens"] = total_candidates
    metrics["aggregated_totals"]["total_overall_tokens"] = total_overall
    metrics["file_statistics"]["yaml_specs_generated"] = yaml_count
    metrics["file_statistics"]["verilog_rtl_files_saved"] = verilog_count

    print("\n" + "-" * 65, file=sys.stderr)
    print("AGGREGATED PERFORMANCE SUMMARY:", file=sys.stderr)
    print(f"  - Aggregated Prompt Cost:    {total_prompt:,} tokens  | Total input instructions and context sent to the model across all agent stages.", file=sys.stderr)
    print(f"  - Aggregated Candidate Cost: {total_candidates:,} tokens  | Total output tokens synthesized by the model representing specifications and Verilog wrappers.", file=sys.stderr)
    print(f"  - Aggregated Token Bill:     {total_overall:,} tokens  | Total combined (input plus output) processing cost consumed during pipeline operations.", file=sys.stderr)
    print(f"  - Generated IP YAML Specs:   {yaml_count} files  | Temporary specification structures generated by the sub-agent for local leaf components.", file=sys.stderr)
    print(f"  - Final Saved Verilog RTL:   {verilog_count} modules  | Completed and separated hardware description modules written into the output directory.", file=sys.stderr)
    
    if "total_pipeline" in durations:
        print(f"  - Total Execution Time:     {durations['total_pipeline']:.2f}s", file=sys.stderr)
    print("=" * 65 + "\n", file=sys.stderr)

    out_metrics_file = output_dir / "pipeline_metrics.json"
    out_metrics_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"[ORCHESTRATOR] Consolidated performance metrics written to: {out_metrics_file}", file=sys.stderr)


# ─── Orchestrator Step Implementations ────────────────────────────────────────

def step1_read_inputs(info):
    """Step 1: Gathers inputs, instructions and structural layout skeletons."""
    arch_path  = Path(info["architecture_doc"])
    tb_path    = Path(info["tb_skeleton"])
    instr_path = REPO_ROOT / "problems" / "easy" / "docs" / "Instructions_for_input.md"
    
    arch_doc = arch_path.read_text(encoding="utf-8") if arch_path.is_file() else ""
    tb_skel  = tb_path.read_text(encoding="utf-8")   if tb_path.is_file()  else ""
    parsing_instr = instr_path.read_text(encoding="utf-8") if instr_path.is_file() else ""
    
    return arch_doc, tb_skel, parsing_instr


def run_yaml_gen_agent(info):
    """
    Sub-agent communication wrapper (Step 2).
    Constructs CLI parameter calls. Clean of skills files.
    """
    temp_dir = Path(info["temp_dir"])
    sub_agent_script = REPO_ROOT / "agent" / "yaml_gen_agent.py"
    manifest_out = temp_dir / "yaml_gen_agent_manifest.json"

    cmd = [
        sys.executable,
        str(sub_agent_script),
        "--problem", info["problem"],
        "--model", info["model"],
        "--model-endpoint", info["model_endpoint"],
        "--temp-dir", str(temp_dir),
        "--arch-doc-path", str(info["architecture_doc"]),
        "--tb-skel-path", str(info["tb_skeleton"]),
        "--instr-path", str(REPO_ROOT / "problems" / "easy" / "docs" / "Instructions_for_input.md"),
        "--manifest-out", str(manifest_out)
    ]

    print(f"[ORCHESTRATOR] Spawning YAML Gen Agent to calculate specs...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ORCHESTRATOR FATAL] YAML Gen Agent crashed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not manifest_out.is_file():
        raise FileNotFoundError(f"[ORCHESTRATOR FATAL] YAML Gen Agent completed, but manifest file is missing: {manifest_out}")

    with open(manifest_out, "r") as f:
        manifest = json.load(f)

    return manifest.get("yaml_blocks", [])


def step3_generate_ip_rtl(info, yaml_blocks):
    """Step 3: Converts extracted YAML specs into structural HDL blocks."""
    output_dir, temp_dir = Path(info["output_dir"]), Path(info["temp_dir"])
    generated = []
    for i, yaml_str in enumerate(yaml_blocks):
        files = rtl_gen_from_yaml(yaml_str, info["rtl_gen_lib"], output_dir, temp_dir, idx=i)
        generated.extend(files)
    return generated


def step3b_generate_ip_testbenches(info, generated_files):
    """Step 3b: Builds modular target block verify testbenches."""
    tb_output_dir = Path("/home/aakarshitha/nxp_workspace/problems/easy/intermediate_tb")
    tb_output_dir.mkdir(parents=True, exist_ok=True)
    
    tb_files_created, type_counts = [], {}
    for file_path_str in generated_files:
        path_obj = Path(file_path_str) if Path(file_path_str).is_absolute() else Path(info["output_dir"]) / file_path_str
        if not path_obj.is_file() or path_obj.suffix != ".v": continue
        content = path_obj.read_text(encoding="utf-8")
        mod_match = re.search(r'\bmodule\s+(\w+)', content)
        if not mod_match: continue
        
        dut_name = mod_match.group(1)
        instance_idx = type_counts.get(dut_name, 0)
        type_counts[dut_name] = instance_idx + 1
        
        ports = extract_ports_from_verilog(content)
        if not ports: continue
            
        tb_source = generate_single_tb(dut_name, instance_idx, ports)
        tb_file_path = tb_output_dir / f"tb_{dut_name}_{instance_idx}.v"
        tb_file_path.write_text(tb_source, encoding="utf-8")
        tb_files_created.append(str(tb_file_path))
        
    return tb_files_created


def run_top_stitch_sub_agent(info, generated_files):
    """
    Sub-agent communication wrapper for SoC Top Stitching (Step 4).
    Invokes agent/top_stitch_agent.py to synthesize the top-level SoC wrapper.
    """
    temp_dir = Path(info["temp_dir"])
    output_dir = Path(info["output_dir"])
    sub_agent_script = REPO_ROOT / "agent" / "top_stitch_agent.py"
    manifest_out = temp_dir / "top_stitch_manifest.json"

    cmd = [
        sys.executable,
        str(sub_agent_script),
        "--problem", info["problem"],
        "--model", info["model"],
        "--model-endpoint", info["model_endpoint"],
        "--temp-dir", str(temp_dir),
        "--output-dir", str(output_dir),
        "--arch-doc-path", str(info["architecture_doc"]),
        "--tb-skel-path", str(info["tb_skeleton"]),
        "--generated-files", ",".join(generated_files),
        "--manifest-out", str(manifest_out)
    ]

    print(f"[ORCHESTRATOR] Spawning SoC Top Stitching Sub-Agent to synthesize wrapper...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ORCHESTRATOR FATAL] Top Stitch Sub-Agent crashed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not manifest_out.is_file():
        raise FileNotFoundError(f"[ORCHESTRATOR FATAL] Top Stitch Sub-agent completed, but manifest file is missing: {manifest_out}")

    with open(manifest_out, "r") as f:
        manifest = json.load(f)

    return manifest.get("soc_response", "")


def step5_save_verilog(info, soc_response):
    """Step 5: Parses output response to isolate and write completed RTL files."""
    output_dir = Path(info["output_dir"])
    saved = []
    for fname, code in extract_verilog_blocks(soc_response):
        fpath = output_dir / fname
        fpath.write_text(code + "\n", encoding="utf-8")
        saved.append(str(fpath))
    return saved


def step6_generate_testbench(info, all_rtl_files, strategy_tips_path):
    """
    Step 6: Spawns the Testbench Generation Sub-Agent, dynamically injecting 
    all 3 skill files from skills/tb_gen_skills/ directory.
    """
    temp_dir = Path(info["temp_dir"])
    sub_agent_script = REPO_ROOT / "agent" / "tb_gen_agent.py"
    manifest_out = temp_dir / "tb_gen_manifest.json"

    # All three skills are placed strictly under skills/tb_gen_skills/ directory
    strategy_skill = REPO_ROOT / "skills" / "tb_gen_skills" / "StrategyStimulusBuilder.skill.md"
    decoder_skill = REPO_ROOT / "skills" / "tb_gen_skills" / "ApbAddressDecoder.skill.md"
    sanitizer_skill = REPO_ROOT / "skills" / "tb_gen_skills" / "VerilogSyntaxSanitizer.skill.md"
    skills_paths_str = f"{strategy_skill},{decoder_skill},{sanitizer_skill}"
    # skills_paths_str = f"{strategy_skill},{decoder_skill}"

    resolved_paths = [str(Path(f).resolve()) for f in all_rtl_files]
    generated_files_str = ",".join(resolved_paths)

    cmd = [
        sys.executable,
        str(sub_agent_script),
        "--problem", info["problem"],
        "--model", info["model"],
        "--model-endpoint", info["model_endpoint"],
        "--temp-dir", str(temp_dir),
        "--output-dir", str(info["output_dir"]),
        "--tb-skel-path", str(info["tb_skeleton"]),
        "--generated-files", generated_files_str,
        "--strategy-tips-path", str(strategy_tips_path),
        "--evaluate-script-path", str(REPO_ROOT / "evaluator" / "evaluate.py"),
        "--manifest-out", str(manifest_out),
        "--skills-paths", skills_paths_str
    ]

    print(f"[ORCHESTRATOR] Spawning Testbench Gen Agent with all 3 skills...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ORCHESTRATOR FATAL] Testbench Gen Agent crashed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not manifest_out.is_file():
        raise FileNotFoundError(f"[ORCHESTRATOR FATAL] Testbench Gen Agent completed, but manifest is missing at: {manifest_out}")

    with open(manifest_out, "r") as f:
        manifest = json.load(f)

    return manifest.get("testbench_path", "")
    
def run_tb_gen_sub_agent(info, generated_files):
    """
    Sub-agent communication wrapper for Testbench Generation (Step 6).
    Invocates agent/tb_gen_agent.py and supplies architectural paths, 
    strategy tips, evaluation configs, and dynamic syntax sanitizers.
    """
    temp_dir = Path(info["temp_dir"])
    output_dir = Path(info["output_dir"])
    sub_agent_script = REPO_ROOT / "agent" / "tb_gen_agent.py"
    manifest_out = temp_dir / "tb_gen_manifest.json"

    # 1. Resolve strategy tips dynamically from workspace configuration rules
    strategy_tips_path = temp_dir / "active_strategy_tips.json"
    try:
        from config.strategy_tips import STRATEGY_TIPS
        tips = STRATEGY_TIPS.get(info["problem"], {})
    except ImportError:
        tips = {
            "ahb_apb_bridge": "Focus on getting the AHB-to-APB bridge timing right (SETUP then ENABLE phase).",
            "apb_fabric": "The APB fabric must correctly decode 4KB address windows.",
            "watchdog": "Watchdog requires the 2-step unlock sequence (magic key = 0xABCD1234).",
            "irq_aggregator": "IRQ aggregator polarity: irq_in = irq_src XOR ~polarity."
        }
    strategy_tips_path.write_text(json.dumps(tips, indent=2), encoding="utf-8")

    # 2. Resolve evaluate.py path dynamically based on problem scope
    eval_path = REPO_ROOT / "problems" / info["problem"] / "eval" / "evaluate.py"
    if not eval_path.is_file():
        eval_path = REPO_ROOT / "problems" / info["problem"] / "evaluate.py"
    if not eval_path.is_file():
        eval_path = REPO_ROOT / "evaluator" / "evaluate.py"
        
    # 3. Resolve active declarative skill paths (Markdown blueprints)
    skills_paths = []
    skills_dir = REPO_ROOT / "skills" / "tb_gen_skills"
    if skills_dir.is_dir():
        for f in skills_dir.glob("*"):
            if f.suffix in [".md", ".py"]:
                skills_paths.append(str(f))
    if not skills_paths:
        fallback_skill = REPO_ROOT / "skills" / "top_stitch_skills" / "VerilogSyntaxSanitizer.skill.md"
        if fallback_skill.is_file():
            skills_paths.append(str(fallback_skill))
        else:
            fallback_dir = temp_dir / "skills"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            skill_file = fallback_dir / "VerilogSyntaxSanitizer.skill.md"
            skill_file.write_text("Declarative syntax guard blueprint.", encoding="utf-8")
            skills_paths.append(str(skill_file))

    # Compile dynamic subprocess CLI parameters pass
    cmd = [
        sys.executable,
        str(sub_agent_script),
        "--problem", info["problem"],
        "--model", info["model"],
        "--model-endpoint", info["model_endpoint"],
        "--temp-dir", str(temp_dir),
        "--output-dir", str(output_dir),
        "--tb-skel-path", str(info["tb_skeleton"]),
        "--generated-files", ",".join(generated_files),
        "--strategy-tips-path", str(strategy_tips_path),
        "--evaluate-script-path", str(eval_path),
        "--manifest-out", str(manifest_out),
        "--skills-paths", ",".join(skills_paths),
        "--arch-doc-path", str(info["architecture_doc"])
    ]

    print(f"[ORCHESTRATOR] Spawning Testbench Generation Sub-Agent to compile verification tests...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ORCHESTRATOR FATAL] Testbench Sub-Agent crashed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not manifest_out.is_file():
        raise FileNotFoundError(f"[ORCHESTRATOR FATAL] Testbench Sub-agent completed, but manifest file is missing: {manifest_out}")

    print(f"[ORCHESTRATOR] Testbench generation completed successfully.", file=sys.stderr)


def call_model_vertexai(endpoint, prompt, model, max_tokens=16384, diagnostics_path=None):
    """URLLib based minimal fallback API client helper to support direct VertexAI connection."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    base_url = endpoint.rstrip("/")
    url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"

    payload_data = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2}
    }
    body = json.dumps(payload_data).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            if diagnostics_path:
                diagnostics_path.write_text(json.dumps({"status": "SUCCESS", "payload": resp_data}, indent=2))
            return resp_data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        if diagnostics_path:
            diagnostics_path.write_text(json.dumps({"status": "ERROR", "error": str(e)}, indent=2))
        raise e


# ─── Main Orchestrator Loop ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="NXP ICLAD 2026 — Master Coordinator Orchestrator")
    parser.add_argument("info_json", help="Path to info.json produced by runner/run_benchmark.py")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--yaml-only", action="store_true", help="Terminate pipeline operations after sub-agent specs gather completes")
    parser.add_argument("--gen-tbs", action="store_true", help="Execute intermediate block verification testbench synthesis loop")
    args = parser.parse_args()

    durations = {}
    total_pipeline_start = time.monotonic()

    with Path(args.info_json).open(encoding="utf-8") as f:
        info = json.load(f)

    if args.model: 
        info["model"] = args.model
        
    if not info.get("model_endpoint"):
        print("[ORCHESTRATOR] Bypassing proxy. Direct Google API connection selected.", file=sys.stderr, flush=True)
        info["model_endpoint"] = "https://generativelanguage.googleapis.com"

    Path(info["output_dir"]).mkdir(parents=True, exist_ok=True)
    temp_dir_path = Path(info["temp_dir"])
    temp_dir_path.mkdir(parents=True, exist_ok=True)

    # Resolve active difficulty context and identify/extract matching strategies
    difficulty = info.get("difficulty", "easy").lower()
    active_tips = STRATEGY_TIPS.get(difficulty, STRATEGY_TIPS.get("easy", {}))

    # Log loaded strategy directives to standard error
    print("\n" + "=" * 65, file=sys.stderr)
    print(f"       ACTIVE STRATEGY DIRECTIVES ({difficulty.upper()} MODE)", file=sys.stderr)
    print("=" * 65, file=sys.stderr)
    if active_tips:
        for module, tip in active_tips.items():
            print(f"  * [{module.upper()}]: {tip}", file=sys.stderr)
    else:
        print("  (No strategy rules compiled for this execution tier)", file=sys.stderr)
    print("=" * 65 + "\n", file=sys.stderr)

    # Save strategy tips inside the scratch directory for sub-agents to digest
    strategy_tips_path = temp_dir_path / "active_strategy_tips.json"
    strategy_tips_path.write_text(json.dumps(active_tips, indent=2), encoding="utf-8")

    # Step 1: Read Inputs
    arch_doc, tb_skel, parsing_instr = step1_read_inputs(info)
    
    # Step 2: Delegate Spec Inference to Sub-Agent
    yaml_start_time = time.monotonic()
    yaml_blocks = run_yaml_gen_agent(info)
    durations["yaml_gen_agent"] = time.monotonic() - yaml_start_time
    
    if args.yaml_only:
        print("[ORCHESTRATOR] Completed YAML isolation. Halting pipeline execution as requested.", file=sys.stderr)
        durations["total_pipeline"] = time.monotonic() - total_pipeline_start
        collect_and_save_metrics(info, durations)
        sys.exit(0)
        
    # Step 3: Run local RTL Generators
    rtl_start_time = time.monotonic()
    generated = step3_generate_ip_rtl(info, yaml_blocks) if yaml_blocks else []
    durations["rtl_generation"] = time.monotonic() - rtl_start_time
    
    # Step 3b: Run Local Testbench Generators (Optional)
    if args.gen_tbs and generated:
        tb_start_time = time.monotonic()
        step3b_generate_ip_testbenches(info, generated)
        durations["testbench_generation"] = time.monotonic() - tb_start_time
    
    # Step 4: Run SoC Top Synthesizer
    stitch_start_time = time.monotonic()
    soc_response = run_top_stitch_sub_agent(info, generated)
    durations["top_stitch_agent"] = time.monotonic() - stitch_start_time
    
    # Step 5: Save compiled Verilog outputs
    save_start_time = time.monotonic()
    saved = step5_save_verilog(info, soc_response)
    durations["verilog_saving"] = time.monotonic() - save_start_time

    if not saved:
        print("[ORCHESTRATOR ERROR] No Verilog files generated!", file=sys.stderr)
        sys.exit(1)

    # # Step 6: Delegate Testbench Refinement and Sanity Verification strictly to dynamic sub-agent with 3 skills
    # tb_gen_start_time = time.monotonic()
    # all_rtl_files = generated + saved
    # tb_file_created = step6_generate_testbench(info, all_rtl_files, strategy_tips_path)
    # durations["tb_gen_agent"] = time.monotonic() - tb_gen_start_time

    # Record total pipeline and generate complete Metrics Report
    # durations["total_pipeline"] = time.monotonic() - total_pipeline_start
    collect_and_save_metrics(info, durations)

    # print(f"[ORCHESTRATOR] Agentic pipeline execution completed successfully. Target testbench ready: {tb_file_created}", file=sys.stderr)
    
    # New one
     # Step 6: Invoke Testbench Generation Sub-Agent with integrated arch specifications
    try:
        run_tb_gen_sub_agent(info, saved)
    except Exception as e:
        print(f"[ORCHESTRATOR ERROR] Testbench Generation Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("[ORCHESTRATOR] Agentic pipeline execution completed successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
