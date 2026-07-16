#!/usr/bin/env python3
"""
NXP ICLAD 2026 — Testbench Generation Sub-Agent
===============================================
Handles Step 6 logic: Extracts test categories from evaluation configuration, 
active strategy tips, and all 3 dynamic declarative skills to construct 
robust testcases. Sanity-checks base alignments, timing loops, and Verilog-2005 styles.
Enforces strict in-block procedural containment and conforms to the Golden Reference Skeleton.
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
import importlib.util
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
            print(f"[TB-AGENT INFO] {message} ({elapsed}s elapsed)", file=sys.stderr, flush=True)

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
            "temperature": 0.1,  # Deterministic synthesis
            "thinkingConfig": {
                "thinkingBudget": 2048
            }
        }
    }

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[TB-AGENT WARN] GEMINI_API_KEY environment variable is not set!", file=sys.stderr, flush=True)

    base_url = endpoint.rstrip("/")
    if ":generateContent" not in base_url:
        url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
    else:
        url = f"{base_url}?key={api_key}" if "?key=" not in base_url else base_url

    body = json.dumps(payload_data).encode("utf-8")
    delay = 2.0
    last_error = None

    for attempt in range(1, max_retries + 1):
        with heartbeat(f"TB-Agent API Turn {attempt}/{max_retries}"):
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
                    print(f"[TB-AGENT FATAL] Non-retryable API status error: {last_error}", file=sys.stderr)
                    break
            except Exception as e:
                last_error = str(e)

        if attempt < max_retries:
            print(f"[TB-AGENT WARN] Call choked ({last_error}). Retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)
            delay *= 2.0

    raise RuntimeError(f"TB-Agent exhausted all retries. Final error: {last_error}")


def fix_missing_begins(code_text):
    """
    Scans testbench code line by line and programmatically adds missing 'begin' 
    statements to category conditionals wrapping sequential blocks.
    """
    lines = code_text.splitlines()
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        # Enforce on any conditional statement lines targeting active evaluation categories
        if stripped.startswith("if") and "begin" not in stripped.lower():
            if "skip_" in stripped or "run_T" in stripped or "RUN_ALL" in stripped:
                line = line.rstrip() + " begin"
        fixed_lines.append(line)
    return "\n".join(fixed_lines)


def sanitize_tasks_begin_end(code_text):
    """
    Ensures that all tasks in the code are correctly formatted with a single
    'begin' keyword after inputs/local variables, and an 'end' right before 'endtask'.
    Does not modify internal logic or variables inside the task block.
    """
    task_pattern = r'(\btask\s+\w+\s*;)(.*?)(endtask)'
    
    def replace_task(match):
        header = match.group(1)
        body = match.group(2)
        footer = match.group(3)
        
        body_lines = body.splitlines()
        last_decl_idx = -1
        for idx, line in enumerate(body_lines):
            stripped = line.strip()
            if not stripped:
                continue
            if any(stripped.startswith(prefix) for prefix in ['input', 'output', 'inout', 'reg', 'wire', 'integer', 'parameter']):
                last_decl_idx = idx
        
        has_begin = False
        next_active_idx = last_decl_idx + 1
        while next_active_idx < len(body_lines):
            stripped_next = body_lines[next_active_idx].strip()
            if stripped_next:
                if stripped_next.startswith('begin'):
                    has_begin = True
                break
            next_active_idx += 1
        
        has_end = False
        prev_active_idx = len(body_lines) - 1
        while prev_active_idx >= 0:
            stripped_prev = body_lines[prev_active_idx].strip()
            if stripped_prev:
                if stripped_prev.startswith('end'):
                    has_end = True
                break
            prev_active_idx -= 1
        
        new_body_lines = list(body_lines)
        if not has_begin:
            insert_pos = last_decl_idx + 1
            new_body_lines.insert(insert_pos, "        begin")
            if prev_active_idx >= insert_pos:
                prev_active_idx += 1
        
        if not has_end:
            new_body_lines.append("        end")
        
        return header + "\n" + "\n".join(new_body_lines) + "\n    " + footer
    
    return re.sub(task_pattern, replace_task, code_text, flags=re.DOTALL | re.IGNORECASE)


def formalize_indentation(text, base_indent_spaces=8):
    """
    Enforces clean, strict standard Verilog formatting on the generated code blocks:
    - Base top-level statements inside the block (comments and 'if' statements) are indented by base_indent_spaces.
    - Nested statements inside 'if begin ... end' are indented by base_indent_spaces + 4.
    - Resolves any unaligned spacing or drift from LLM hallucination.
    """
    lines = text.splitlines()
    cleaned_lines = []
    current_nest = 0
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
            
        # Count begins and ends excluding comments
        line_no_comments = re.sub(r'//.*', '', stripped)
        line_no_comments = re.sub(r'/\*.*?\*/', '', line_no_comments)
        
        begins = len(re.findall(r'\bbegin\b', line_no_comments))
        ends = len(re.findall(r'\bend\b', line_no_comments))
        
        # Determine if this line starts with a closing block keyword
        is_closing_line = stripped.startswith("end") or stripped.startswith("else")
        
        if is_closing_line:
            local_nest = max(0, current_nest - 1)
        else:
            local_nest = current_nest
            
        current_nest += (begins - ends)
        if current_nest < 0:
            current_nest = 0
            
        indent_str = " " * (base_indent_spaces + (local_nest * 4))
        cleaned_lines.append(indent_str + stripped)
        
    return "\n".join(cleaned_lines)


# ─── Helper Functions ─────────────────────────────────────────────────────────
def clean_and_extract_verilog(text):
    """
    Cleans structural code block syntax. Strips away Markdown wraps,
    redundant outer module declarations, and duplicated standard variables.
    """
    # Clean non-breaking space (NBSP) characters
    text = text.replace('\xa0', ' ').replace('\u00a0', ' ')

    pattern = r'`{3}(?:verilog|v)?\s*\n(.*?)`{3}'
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    code = matches[0].strip() if matches else text.strip()

    # Clean any accidental timescale directives to prevent nested directive errors
    code = re.sub(r'`timescale\s+\d+\s*\w+\s*/\s+\d+\s*\w+', '', code, flags=re.IGNORECASE)

    # Scrub out nested module declarations
    code = re.sub(r'module\s+\w+\s*\(.*?\)\s*;', '', code, flags=re.IGNORECASE)
    code = re.sub(r'\bmodule\s+\w+\s*;', '', code, flags=re.IGNORECASE)
    code = re.sub(r'\bendmodule\b', '', code, flags=re.IGNORECASE)

    # Strip procedural block wrappers safely while retaining comments
    stripped_for_boundary = re.sub(r'//.*', '', code)
    stripped_for_boundary = re.sub(r'/\*.*?\*/', '', stripped_for_boundary, flags=re.DOTALL).strip()
    
    starts_with_wrapper = False
    wrapper_type = ""
    
    match_initial_begin = re.match(r'^\s*initial\s+begin\b', stripped_for_boundary, re.IGNORECASE)
    match_initial = re.match(r'^\s*initial\b', stripped_for_boundary, re.IGNORECASE)
    match_begin = re.match(r'^\s*begin\b', stripped_for_boundary, re.IGNORECASE)
    
    if match_initial_begin:
        starts_with_wrapper = True
        wrapper_type = "initial begin"
    elif match_initial:
        starts_with_wrapper = True
        wrapper_type = "initial"
    elif match_begin:
        starts_with_wrapper = True
        wrapper_type = "begin"
        
    ends_with_wrapper = re.search(r'\bend\s*$', stripped_for_boundary, re.IGNORECASE)
    
    if starts_with_wrapper and ends_with_wrapper:
        if wrapper_type == "initial begin":
            code = re.sub(r'^\s*initial\s+begin\b', '', code, count=1, flags=re.IGNORECASE)
            code = re.sub(r'\bend\s*(?://.*|/\*.*?\*/\s*)*$', '', code.strip(), flags=re.IGNORECASE | re.DOTALL)
        elif wrapper_type == "initial":
            code = re.sub(r'^\s*initial\b', '', code, count=1, flags=re.IGNORECASE)
        elif wrapper_type == "begin":
            code = re.sub(r'^\s*begin\b', '', code, count=1, flags=re.IGNORECASE)
            code = re.sub(r'\bend\s*(?://.*|/\*.*?\*/\s*)*$', '', code.strip(), flags=re.IGNORECASE | re.DOTALL)

    # Clean duplicate register and wire declarations that are already declared globally
    duplicated_signals = [
        'clk', 'rst_n', 'presetn', 'pclk', 'cpu_hresp', 'local_errors', 'error_count',
        'rd', 'rs', 'rd_data', 'cpu_hadid', 'cpu_haddr', 'cpu_hwdata', 
        'cpu_hrdata', 'cpu_hwrite', 'cpu_hsel', 'cpu_hready'
    ]
    for sig in duplicated_signals:
        code = re.sub(r'\b(?:reg|wire|integer)\s+(?:\[[^\]]*\]\s*)?\b' + sig + r'\b\s*;', '', code, flags=re.IGNORECASE)

    # Enforce conditional wrapping begin alignments
    code = fix_missing_begins(code)

    return code.strip()


# ─── Core Logic Step 6 Execution ──────────────────────────────────────────────
def run_testbench_generation(args):
    temp_dir = Path(args.temp_dir)
    output_dir = Path(args.output_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read structural files and instruction assets
    tb_skel_path = Path(args.tb_skel_path)
    if not tb_skel_path.is_file():
        raise FileNotFoundError(f"Target testbench skeleton file not found at: {tb_skel_path}")
    tb_skeleton_content = tb_skel_path.read_text(encoding="utf-8")

    # 1b. Read architecture document for register specs and permissions
    arch_doc_path = Path(args.arch_doc_path)
    if not arch_doc_path.is_file():
        raise FileNotFoundError(f"Target architecture document not found at: {arch_doc_path}")
    arch_doc_content = arch_doc_path.read_text(encoding="utf-8")

    # Clean NBSP from skeleton template
    tb_skeleton_content = tb_skeleton_content.replace('\xa0', ' ').replace('\u00a0', ' ')

    # Programmatic Syntax Safeguard 3: Convert invalid tb module body port declarations (input/output)
    def replace_input(m):
        leading = m.group(1)
        size = m.group(2) if m.group(2) else ""
        name = m.group(3)
        return f"{leading}reg         {size}{name};"

    def replace_output(m):
        leading = m.group(1)
        size = m.group(2) if m.group(2) else ""
        name = m.group(3)
        return f"{leading}wire        {size}{name};"

    task_idx = tb_skeleton_content.lower().find("task")
    if task_idx != -1:
        pre_task = tb_skeleton_content[:task_idx]
        post_task = tb_skeleton_content[task_idx:]
        pre_task = re.sub(
            r'^([ \t]*)input\s+(?:wire\s+|reg\s+)?(\[[^\]]+\]\s*)?(\w+)\s*;',
            replace_input,
            pre_task,
            flags=re.MULTILINE | re.IGNORECASE
        )
        pre_task = re.sub(
            r'^([ \t]*)output\s+(?:wire\s+|reg\s+)?(\[[^\]]+\]\s*)?(\w+)\s*;',
            replace_output,
            pre_task,
            flags=re.MULTILINE | re.IGNORECASE
        )
        tb_skeleton_content = pre_task + post_task
    else:
        tb_skeleton_content = re.sub(
            r'^([ \t]*)input\s+(?:wire\s+|reg\s+)?(\[[^\]]+\]\s*)?(\w+)\s*;',
            replace_input,
            tb_skeleton_content,
            flags=re.MULTILINE | re.IGNORECASE
        )
        tb_skeleton_content = re.sub(
            r'^([ \t]*)output\s+(?:wire\s+|reg\s+)?(\[[^\]]+\]\s*)?(\w+)\s*;',
            replace_output,
            tb_skeleton_content,
            flags=re.MULTILINE | re.IGNORECASE
        )

    # 2. Parse evaluate.py to dynamic dictionary mapping
    eval_path = Path(args.evaluate_script_path)
    if not eval_path.is_file():
        raise FileNotFoundError(f"Evaluation blueprint reference script missing at: {eval_path}")

    spec = importlib.util.spec_from_file_location("evaluate", str(eval_path))
    eval_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eval_module)
    problems_cfg = getattr(eval_module, "PROBLEMS", {})
    
    current_problem_cfg = problems_cfg.get(args.problem, {})
    categories = current_problem_cfg.get("categories", {})
    created_tb_rel_path = current_problem_cfg.get("created_tb", "problems/easy/tb/new_testbench.v")

    # 3. Read strategy tips dictionary mapping JSON
    tips_path = Path(args.strategy_tips_path)
    if not tips_path.is_file():
        raise FileNotFoundError(f"Strategy tips manifest file missing at: {tips_path}")
    strategy_tips = json.loads(tips_path.read_text(encoding="utf-8"))

    # 4. Load dynamic declarative skill markdown files strictly from argument paths
    skills_context = ""
    skills_list = [s.strip() for s in args.skills_paths.split(",") if s.strip()]
    for s_path in skills_list:
        p = Path(s_path)
        if p.is_file():
            content = p.read_text(encoding="utf-8")
            skills_context += f"\n================================================================================\n"
            skills_context += f"DECLARATIVE SKILL BLUEPRINT: {p.name}\n"
            skills_context += f"================================================================================\n"
            skills_context += content + "\n"

    # 5. Read RTL context
    rtl_modules_context = ""
    generated_paths = [p.strip() for p in args.generated_files.split(",") if p.strip()] if args.generated_files else []
    
    for f in generated_paths:
        fpath = Path(f) if Path(f).is_absolute() else output_dir / f
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            mod_match = re.search(r'(\bmodule\s+\w+.*?;\s*)', content, re.DOTALL)
            ticks = '`' * 3
            rtl_modules_context += f"\n### Module ({fpath.name}):\n{ticks}verilog\n{mod_match.group(1) if mod_match else content[:600]}\n{ticks}\n"

    # 6. Format prompt with dynamic inputs and simplified, high-impact guardrails
    categories_str = json.dumps(categories, indent=2)
    tips_str = json.dumps(strategy_tips, indent=2)
    ticks = '`' * 3

    prompt = f"""
NXP ICLAD 2026 Verification Test Generator
============================================

You are a Verification Engineer writing test stimulus for a System-on-Chip design in Verilog-2005.

--- 1. ACTIVE IP MODULES & SoC CONTRACTS ---
{rtl_modules_context}

--- 2. REQUIRED TEST CATEGORIES & NUMERICAL SCOPE ---
{ticks}json
{categories_str}
{ticks}

--- 3. STRATEGIC DESIGN TIPS & CRITICAL BEHAVIORS ---
{ticks}json
{tips_str}
{ticks}

--- 4. INJECTED SKILL BLUEPRINTS ---
{skills_context}

--- 5. REGISTER SPECIFICATIONS & ACCESS CONSTRAINTS ---
{ticks}html
{arch_doc_content}
{ticks}

--- 6. ACTUAL TESTBENCH SKELETON TEMPLATE ---
{ticks}verilog
{tb_skeleton_content}
{ticks}

================================================================================
CRITICAL VERILOG-2005 GUARDRAILS (NON-NEGOTIABLE)
================================================================================
1. STRICT VERILOG-2005 ONLY: Absolutely no SystemVerilog constructs. Do NOT use logic, bit, byte, int, or implicit port mappings (.*). Use only standard reg, wire, and integer types.
2. MANDATORY BEGIN-END FOR ALL CONDITIONALS (NO NAKED IF/ELSE): Every 'if' and 'else' statement you generate MUST use an explicit 'begin ... end' block wrapper, even for single-line statements.
3. USE ONLY SKELETON TASKS: Do NOT declare or define your own tasks or functions. Use only the pre-defined helper tasks present in the skeleton (like 'ahb_write' and 'ahb_read').
4. NO IN-BLOCK VARIABLE DECLARATIONS: Do NOT declare any registers, wires, or variables inside the block. Use only globally pre-declared registers (such as 'rd', 'rs', and 'local_errors') for tracking and operations.
5. NO STRUCTURAL WRAPPERS: Do NOT wrap your output in 'module/endmodule' or 'initial begin/end' blocks. Provide ONLY the sequential checks to replace the placeholder comment.
6. COMPACT TESTCASE WRAPPER CONVENTION: Every test case 'Txxx' belonging to '<category_name>' must be wrapped exactly as:
   if (!skip_<category_name> && (RUN_ALL || run_Txxx)) begin
       local_errors = 0;
       $display("[SUITE] Starting Txxx...");
       // Transaction stimulus here...
       if (local_errors == 0) begin
           $display("[PASS] Txxx");
       end else begin
           $display("[FAIL] Txxx");
       end
   end
7. COMPARISON SAFETY: Always use case-equality (=== or !==) when comparing read data to expected values to catch uninitialized (X) or high-impedance (Z) states.
8. RIGID INDENTATION: Indent the 'if (!skip...' block exactly by 8 spaces. Indent all internal statements inside the block exactly by 12 spaces. Keep closing 'end' statements vertically aligned with their starting conditions.
9. ABSOLUTE COMPLETION MANDATE (NO LAZINESS): You must output a fully implemented physical Verilog block for EVERY SINGLE test ID listed in the categories JSON (all 22 tests from T101 to T802). You are strictly forbidden from skipping any test IDs, using comments as placeholders (e.g., '// TODO: Implement T103'), or abbreviating your output. Every test ID must have its own active, complete stimulus checks written out.

================================================================================
REFERENCE EXAMPLE: CORRECT STIMULUS AND ALIGNMENT
================================================================================
{ticks}verilog
        if (!skip_basic_rw && (RUN_ALL || run_T102)) begin
            local_errors = 0;
            $display("[SUITE] Starting T102: Contiguous Writes...");
            ahb_write(32'h0000_1008, 32'h1111_2222, 3'b001);
            if (cpu_hresp == 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T102");
            end else begin
                $display("[FAIL] T102");
            end
        end
{ticks}

Provide ONLY the sequential Verilog check blocks that should replace the 'YOUR SANITY CHECKS HERE' placeholder comment.
"""

    # 7. Request code compilation via API
    print(f"[TB-AGENT] Submitting test stimulus compilation sequence with integrated skills...", file=sys.stderr)
    diagnostics_path = temp_dir / "tb_gen_diagnostics.json"
    response = call_model_vertexai(
        args.model_endpoint, 
        prompt, 
        args.model, 
        diagnostics_path=diagnostics_path
    )
    
    (temp_dir / "tb_response.txt").write_text(response, encoding="utf-8")

    # 8. Extract the Verilog segment and merge it into the skeleton
    injected_verilog = clean_and_extract_verilog(response)
    
    # Locate the structural placeholder comment block and extract base indentation dynamically
    completed_testbench_content = tb_skeleton_content
    placeholder_regex = re.compile(
        r'^([ \t]*)(?://|/\*)\s*[-─=\s]*YOUR SANITY CHECKS HERE[-─=\s]*(?:\*/)?.*$', 
        re.MULTILINE | re.IGNORECASE
    )
    match = placeholder_regex.search(tb_skeleton_content)
    
    if match:
        indent = match.group(1) if match.group(1) else '        '
        base_indent_spaces = len(indent)
        aligned_verilog = formalize_indentation(injected_verilog, base_indent_spaces)
        placeholder_line = match.group(0)
        completed_testbench_content = tb_skeleton_content.replace(
            placeholder_line, 
            f"{placeholder_line}\n{aligned_verilog}"
        )
        print(f"[TB-AGENT] Successfully inserted testcases below placeholder line with formal alignment mapping.", file=sys.stderr)
    else:
        # Fallback 1: Re-try using the line-break pattern
        print(f"[TB-AGENT WARN] Could not locate exact placeholder comment line. Attempting fallback matching.", file=sys.stderr)
        fallback_pattern = r'((?P<indent>\s*)(?://|/\*)\s*[-─=\s]*YOUR SANITY CHECKS HERE[-─=\s]*(?:\*/)?\s*\n)'
        def replace_fallback(m):
            indent = m.group('indent') if 'indent' in m.groupdict() else '        '
            aligned_verilog = formalize_indentation(injected_verilog, len(indent))
            return f"{m.group(1)}{aligned_verilog}\n\n"
            
        completed_testbench_content, count = re.subn(
            fallback_pattern,
            replace_fallback,
            tb_skeleton_content,
            flags=re.IGNORECASE
        )
        if count == 0:
            print(f"[TB-AGENT WARN] Could not locate any placeholder. Appending inside endmodule.", file=sys.stderr)
            aligned_verilog = formalize_indentation(injected_verilog, 4)
            completed_testbench_content = re.sub(
                r'endmodule\s*$',
                f"\ninitial begin\n{aligned_verilog}\nend\n\nendmodule",
                tb_skeleton_content,
                flags=re.IGNORECASE
            )

    # Programmatic Syntax Safeguard 4: Declare tracking and control parameters matching Golden Skeleton
    needed_decls = ""
    if not re.search(r'\bRUN_ALL\b', tb_skeleton_content):
        needed_decls += "    reg        RUN_ALL             = 1; // Set to 1 to run all tests, 0 to run selectively\n\n"
        
    categories_list = []
    if isinstance(categories, dict):
        categories_list = list(categories.keys())
    elif isinstance(categories, list):
        for cat in categories:
            if isinstance(cat, dict):
                categories_list.append(cat.get("name", "unknown"))
            elif isinstance(cat, str):
                categories_list.append(cat)
                
    standard_categories = [
        "basic_rw", "uart_tx", "gpio_irq", "timer", 
        "watchdog", "privilege", "irq_aggregator", "reset_sync"
    ]
    for cat in standard_categories:
        if cat not in categories_list:
            categories_list.append(cat)

    needed_decls += "    // Category Skip Flags (0 = Run this category, 1 = Skip)\n"
    for cat_name in categories_list:
        if not re.search(r'\bskip_' + re.escape(cat_name) + r'\b', tb_skeleton_content):
            needed_decls += f"    reg        skip_{cat_name:<20} = 0;\n"
    needed_decls += "\n"

    test_ids = []
    if isinstance(categories, dict):
        for cat_name, cat_info in categories.items():
            if isinstance(cat_info, dict):
                r = cat_info.get("range", [])
            elif isinstance(cat_info, (list, tuple)):
                r = cat_info
            else:
                r = []
            if len(r) == 2:
                try:
                    for tid in range(int(r[0]), int(r[1]) + 1):
                        test_ids.append((cat_name, tid))
                except Exception:
                    pass
    elif isinstance(categories, list):
        for cat in categories:
            if isinstance(cat, dict):
                cat_name = cat.get("name", "unknown")
                r = cat.get("range", [])
                if len(r) == 2:
                    try:
                        for tid in range(int(r[0]), int(r[1]) + 1):
                            test_ids.append((cat_name, tid))
                    except Exception:
                        pass

    standard_ranges = {
        "basic_rw": [101, 104],
        "uart_tx": [201, 203],
        "gpio_irq": [301, 303],
        "timer": [401, 403],
        "watchdog": [501, 502],
        "privilege": [601, 603],
        "irq_aggregator": [701, 702],
        "reset_sync": [801, 802]
    }
    for cat, r in standard_ranges.items():
        for tid in range(r[0], r[1] + 1):
            if not any(t[1] == tid for t in test_ids):
                test_ids.append((cat, tid))

    test_ids.sort(key=lambda x: x[1])

    needed_decls += "    // Individual Test Run Flags (1 = Run, 0 = Do Not Run)\n"
    current_cat = ""
    for cat_name, tid in test_ids:
        if cat_name != current_cat:
            current_cat = cat_name
            needed_decls += f"    // CATEGORY: {cat_name.upper().replace('_', ' ')}\n"
        if not re.search(r'\brun_T' + str(tid) + r'\b', tb_skeleton_content):
            needed_decls += f"    reg        run_T{tid:<21} = 1;\n"
    needed_decls += "\n"

    # Ensure standard evaluation registers are declared strictly by checking their actual DECLARATION, not just usage
    baseline_regs = ""
    if not re.search(r'\b(?:reg|wire)\s+(?:\[[^\]]*\]\s*)?\brd\b', tb_skeleton_content):
        baseline_regs += "    reg [31:0]  rd;\n"
    if not re.search(r'\b(?:reg|wire)\s+(?:\[[^\]]*\]\s*)?\brs\b', tb_skeleton_content):
        baseline_regs += "    reg [1:0]   rs;\n"
    if not re.search(r'\binteger\s+\blocal_errors\b', tb_skeleton_content):
        baseline_regs += "    integer     local_errors;\n"
    if not re.search(r'\binteger\s+\berror_count\b', tb_skeleton_content):
        baseline_regs += "    integer     error_count         = 0;\n"

    if baseline_regs:
        needed_decls += "    // Baseline Simulation Registers\n" + baseline_regs

    if needed_decls:
        decl_block = f"""    // =========================================================================
    // TEST SUITE CONTROL FLAGS (Fixes "Unable to bind wire/reg/memory" errors)
    // =========================================================================
{needed_decls}"""

        module_header_match = re.search(r'\bmodule\s+\w+\s*(?:\x28[^\x29]*\x29)?\s*;', completed_testbench_content)
        if module_header_match:
            insert_pos = module_header_match.end()
            completed_testbench_content = (
                completed_testbench_content[:insert_pos] + 
                "\n\n" + decl_block + "\n" + 
                completed_testbench_content[insert_pos:]
            )
            print("[TB-AGENT] Successfully inserted control variables right after the module header.", file=sys.stderr)
        else:
            insertion_match = re.search(r'^\s*(always|initial|task|function|parameter)\b', completed_testbench_content, re.MULTILINE | re.IGNORECASE)
            if insertion_match:
                idx = insertion_match.start()
                completed_testbench_content = completed_testbench_content[:idx] + decl_block + "\n" + completed_testbench_content[idx:]
                print("[TB-AGENT] Fallback 1: Inserted control variables before procedural / task declarations.", file=sys.stderr)
            else:
                completed_testbench_content = re.sub(
                    r'(\bendmodule\b)',
                    decl_block + r'\n\1',
                    completed_testbench_content,
                    completed_testbench_content,
                    flags=re.IGNORECASE
                )
                print("[TB-AGENT] Fallback 2: Inserted control variables before endmodule.", file=sys.stderr)

    # Programmatic Syntax Safeguard 5: Correct Timescale placement
    completed_testbench_content = re.sub(
        r'^\s*`timescale\s+\d+\s*\w+\s*/\s+\d+\s*\w+\s*$', 
        '', 
        completed_testbench_content, 
        flags=re.MULTILINE | re.IGNORECASE
    )
    completed_testbench_content = completed_testbench_content.strip()
    
    if not completed_testbench_content.startswith("`timescale"):
        completed_testbench_content = "`timescale 1ns / 1ps\n\n" + completed_testbench_content

    completed_testbench_content = sanitize_tasks_begin_end(completed_testbench_content)

    # 9. Save completed testbench directly to target evaluate file path
    tb_path_obj = REPO_ROOT / created_tb_rel_path
    tb_path_obj.parent.mkdir(parents=True, exist_ok=True)
    tb_path_obj.write_text(completed_testbench_content, encoding="utf-8")

    # 10. Output complete Manifest
    manifest_data = {
        "testbench_path": str(tb_path_obj),
        "status": "SUCCESS"
    }

    manifest_out_path = Path(args.manifest_out)
    manifest_out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_out_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    print(f"[TB-AGENT] Verification suite compilation completed. Testbench saved to: {tb_path_obj}", file=sys.stderr)


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sub-Agent tasking dynamic simulation checks compilation")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-endpoint", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tb-skel-path", required=True)
    parser.add_argument("--generated-files", required=True, help="Comma-separated list of generated RTL module paths")
    parser.add_argument("--strategy-tips-path", required=True, help="Path to JSON file containing strategy rules")
    parser.add_argument("--evaluate-script-path", required=True, help="Path to evaluate.py script")
    parser.add_argument("--manifest-out", required=True)
    parser.add_argument("--run-id", default=None, help="Optional run identifier")
    parser.add_argument("--skills-paths", required=True, help="Comma-separated list of active declarative skill Markdown files")
    parser.add_argument("--arch-doc-path", required=True, help="Path to architecture document")

    args = parser.parse_args()
    try:
        run_testbench_generation(args)
        sys.exit(0)
    except Exception as e:
        print(f"[TB-AGENT ERROR] Execution failed: {e}", file=sys.stderr)
        sys.exit(1)
