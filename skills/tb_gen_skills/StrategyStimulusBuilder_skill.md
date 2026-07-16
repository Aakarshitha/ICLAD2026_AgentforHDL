id: strategy_stimulus_builder
name: StrategyStimulusBuilder
description: "Instructs the Testbench Agent on how to programmatically convert natural language strategy tips into robust, synthesizable Verilog-2005 test sequences."
version: "1.0.0"
category: "verification_stimulus"
tags:

testbench

verilog-2005

verification-engineering
inputs:
active_strategy_tips: "A JSON file (active_strategy_tips.json) containing category-wise strategy tips based on difficulty (easy, medium, hard)."
tb_skeleton: "The system's master testbench template file (skeleton.v) containing ready-to-use bus-driver tasks like ahb_write and ahb_read."
test_categories: "The dynamic list of active categories (e.g., basic_rw, watchdog, gpio_irq) and test ranges parsed from evaluate.py."
outputs:
sequential_stimulus_block: "Synthesizable, sequential Verilog-2005 code ready to replace the // Your sanity checks here placeholder."

Skill Overview

The StrategyStimulusBuilder skill instructs the agent on how to translate human-engineered strategic guidelines (such as 2-step watchdog unlock sequences or XOR interrupt polarity checks) into precise, structured stimulus blocks. It prevents the agent from making arbitrary assumptions about register sequences and ensures the generated tests align directly with the criteria used by the hidden design evaluator.

Agent Instructions & Reasoning Steps

When executing this skill, you must process the input files and reason through the stimulus generation using the following steps:

Step 1: Parse the Strategic Directives

Locate and read the active_strategy_tips.json file.

Identify the active difficulty context (e.g., "easy", "medium", or "hard").

Read the bulleted strategy tips mapped to your active difficulty tier.

Placeholder Rule: Treat each strategy tip as a direct behavioral constraint. If a tip references a specific IP module (e.g., "Watchdog requires the 2-step unlock sequence (magic key = 0xABCD1234)"), you must prepare to apply this exact transaction pattern when generating tests for that IP's ID range.

Step 2: Correlate Test IDs with Strategy Rules

Retrieve the test_categories mapping from evaluate.py.

For each active test ID range, identify which IP block and strategy rule it targets:

Test IDs in the 101-105 range map to Basic Read/Write checks.

Test IDs in the 501-503 range map to Watchdog checks.

Test IDs in the 701-703 range map to Interrupt Aggregator checks.

When synthesizing a specific test ID (e.g., T501), do not write arbitrary code. You must locate the corresponding tip and use its listed constraints (such as the exact unlock sequence address offsets and keys).

Step 3: Implement Sequentially inside Initial Block

Leverage the existing driver tasks declared in the tb_skeleton (specifically ahb_write(address, data, size_code) and ahb_read(address, size_code, read_data, response_status)).

Do NOT declare any variables, registers, or clocks that already exist in the skeleton.

Structure every single test scenario using standard Verilog conditional wrappers to support targeted simulation runs:

if (!skip_category_name && (RUN_ALL || run_Txxx)) begin
    // Step A: Initialize local error counter
    local_errors = 0;
    $display("[SUITE] Starting Txxx: Descriptive Name...");

    // Step B: Write stimulus sequence using driver tasks
    ahb_write(base_address + offset, data_payload, size_code);
    if (cpu_hresp == 2'b01) local_errors = local_errors + 1; // Catch bus response errors

    // Step C: Verify read-back or state expectations using !== (case inequality)
    ahb_read(base_address + offset, size_code, rd, rs);
    if (rs == 2'b01 || rd !== expected_value) begin
        $display("[ERROR] Txxx mismatch! Expected: 0x%0h, Got: 0x%0h", expected_value, rd);
        local_errors = local_errors + 1;
    end

    // Step D: Report PASS/FAIL in the exact format required by evaluate.py
    if (local_errors == 0) $display("[PASS] Txxx");
    else                   $display("[FAIL] Txxx");
end


Reference Patterns & Verification Templates

Example: Watchdog 2-Step Unlock (Strategic Rule)

When the active tip demands a 2-step unlock sequence using a magic key (0xABCD1234), your reasoning cycle must generate the following stimulus sequence:

// Watchdog Unlock Sequence Stimulus Pattern
ahb_write(32'h0000_5008, 32'hABCD_1234, 3'b001); // Step 1: Write magic key to unlock register
ahb_write(32'h0000_5000, 32'h0000_0001, 3'b001); // Step 2: Modify watchdog control parameters


Example: Interrupt Aggregator XOR Polarity Checks

When testing input polarity verification (irq_in = irq_src XOR ~polarity), you must toggle the source signals and polarity configurations and assert the expected outputs:

// Polarity Toggle Stimulus Pattern
ahb_write(32'h0000_7004, 32'h0000_0000, 3'b001); // Set polarity active-low (inverting)
// Drive interrupt source inputs externally and check expected aggregator logic output ...

