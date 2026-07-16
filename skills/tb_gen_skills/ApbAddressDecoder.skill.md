id: apb_address_decoder
name: ApbAddressDecoder
description: "Guides the YAML Generation Agent in extracting base addresses, register offsets, and memory alignment constraints from architectural documents."
version: "1.0.0"
category: "specification_parsing"
tags:

specification

address-decoding

yaml-metadata
inputs:
architecture_doc: "The raw markdown/HTML document (architecture.md) detailing the system's memory map and registers."
tb_skeleton: "The master testbench skeleton containing top-level module instances to cross-verify signal interfaces."
outputs:
json_register_map: "A structured registry mapping each block's base address, range, offsets, permissions, and byte-widths."

Skill Overview

The ApbAddressDecoder skill is a behavioral contract that instructs the YAML Generation Agent on how to extract system address alignments from architectural specifications. It replaces noisy, token-heavy documentation tables with standard JSON maps, preventing common LLM mistakes like decimal-to-hex errors, bus alignment issues, and memory overlaps.

Agent Instructions & Reasoning Steps

When using this skill to parse specifications, you must reason through the data map using the following steps:

Step 1: Parse the Memory Map Base Addresses

Scan the architecture_doc for table layouts, HTML codes, or list bullet markers indicating peripheral memory maps.

Isolate each peripheral block (e.g., gpio, uart, timer, watchdog).

Extract the base address and range size (e.g., 0x40001000 to 0x40001FFF).

Alignment Rule: Verify that each base address is aligned to the standard 4KB APB fabric boundary. The result of base modulo 4096 (or 0x1000 in hexadecimal) must be 0. If you encounter an address that violates this alignment, flag it inside your diagnostic logs.

Step 2: Map Register Offsets and Access Attributes

For each peripheral block, extract all registers, their hexadecimal offsets from the base address, byte widths, and access rules (Read-Write RW, Read-Only RO, or Write-Only WO).

Ensure offsets do not exceed the boundaries of the decoded 4KB window.

Convert any decimal addresses found in raw text into standardized 32-bit hexadecimal formats (e.g., convert 4096 to 32'h1000).

Step 3: Format into standard YAML Peripheral Specs

Once the memory layout is resolved, do not emit plain text explanations. Format each peripheral into a structured YAML block containing its dynamic parameters:

name: peripheral_instance_name
ip_type: supported_ip_type
parameters:
  APB_ADDR_WIDTH: 12
  APB_DATA_WIDTH: 32
  BASE_ADDR: "32'h0000_1000"
  REG_OFFSET_CTRL: "12'h000"
  REG_OFFSET_DATA: "12'h004"


Cross-reference the master tb_skeleton to ensure the generated parameters match the signal interfaces instantiated on the top-level SoC.

Validation Checklist

Before finalizing the decoded specifications, check them against the following layout rules:

[ ] No two peripheral base addresses overlap or share the same address window.

[ ] All registers are mapped within their defined 4KB address spaces.

[ ] Address representations use standard, compilable Verilog formats (e.g., 32'h0000_1000 instead of raw decimal numbers).
