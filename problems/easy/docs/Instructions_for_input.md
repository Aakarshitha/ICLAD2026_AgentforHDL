### Multimodal Hardware Architecture Extraction Protocol (MHAEP)

```
[Phase 1: DOM Semantic Analysis] ──> [Phase 2: Spatial SVG Ingestion] ──> [Phase 3: Deep Attribute Extraction] ──> [Phase 4: Safety & Conflict Check]

```

#### Phase 1: DOM Semantic Analysis (Textual Context)

1. Extract structural page hierarchy using headers (`<h1>`-`<h3>`), navigation arrays (`<nav>`), and sectional divisions (`class="sec"`).
2. Parse problem statements and deliverables blocks **first** to establish execution scope, compilation targets, and architectural constraints.
3. Ingest unstructured prose and explicit directives (`class="co"`, `class="ps"`) into an environmental configuration database.
4. Convert HTML tables (`<table>`) directly into structured data maps containing memory addresses and register layouts.

#### Phase 2: Spatial & Structural SVG Ingestion (Visual Topology)

5. Isolate all `<svg>` nodes. Treat source code primitives (`<g>`, `<path>`, `<polygon>`, `<ellipse>`, `<rect>`) as explicit, executable structural layouts rather than raw pixels.
6. Map viewport coordinate properties (`viewBox`) and grouping hierarchies (`<g>`) to determine parent-child functional block structures.

#### Phase 3: Deep Attribute & Parameter Derivation Extraction

7. Trace vector parent clusters (`class="cluster"` or grouped enclosing boundary shapes) to establish physical subsystem limits, power domains, or clock networks.
8. Apply structural parent properties implicitly to all interior sub-blocks unless local overrides are found.
9. Inspect line stroke arrays (`stroke-dasharray`): convert **solid vectors** to synchronous interfaces/bus matrices, and **dashed/dotted vectors** to asynchronous loops, side-bands, or interrupts.
10. Extract line directionality by converting arrowhead geometries (`<polygon points="...">`) into explicit driver-source and receiver-sink definitions.
11. Convert line vector text containing array bit brackets (e.g., `[31:12]`) directly into multi-bit parallel bus width specifications.
12. Decode flowchart and block shapes explicitly:
* **Sharp Rectangles:** Dedicated execution engines, physical hardware blocks, or register banks.
* **Rhombuses / Diamonds:** Condition evaluation centers, address decoders, or state transitions (e.g., `pprot[0] == 1?`).
* **Ellipses / Circles:** System-level pin interfaces, I/O ports, global status sources, or infrastructure nets (e.g., `sys_rst_n`).


13. Mine embedded string primitives for strict parametric values: queue/FIFO depths, width scalars, bit-field indices, latency constants, and literal initialization configuration keys (e.g., `0xABCD_1234`).
14. **Multi-Source Parameter Derivation Assembly Rule**: When a configuration field is noted as dependent on specific internal control register architectures, execute a joint lookup across text blocks, tables, and visual strings:
* **Text Formula Analysis**: Locate explicit mathematical formulations inside descriptions (e.g., `baud_rate = clk / (16 × (baud_div+1))`) to parse the algorithmic function of the variable.
* **Table Bit-Field Slicing**: Match variables directly back to their location fields in register map tables. For instance, if an assignment mandates tracking `default_div` via the `CTRL` register, trace the bit definitions precisely to find the bit index slice location mapping (e.g., `[23:8] = baud_div`). Use these structural details to derive the static compile-time baseline parameter initialization constraint.



#### Phase 4: Safety & Conflict Check (Silicon Validation)

15. Cross-reference textural maps against visual signal nets to resolve hidden parameters or clear architectural omissions.

---

### 2. Dynamic Semantic Conflict Resolution Hierarchy

If textual descriptions, register tables, or structural diagrams contain contradicting engineering data, apply a deterministic tie-breaking cascade:

$$\text{Priority 1 (Absolute): Literal SVG Labels \& Signal Primitives}$$

$$\Downarrow$$

$$\text{Priority 2: Structured HTML Register Tables \& Address Maps}$$

$$\Downarrow$$

$$\text{Priority 3 (Lowest): General Textual Prose \& Section Descriptions}$$

* **Guardrail:** If an irreconcilable conflict occurs within the same priority tier, halt compilation/extraction and generate a formal error log to the operator. Do not select parameters arbitrarily.

---

### 3. Anti-Over-Study & Scope Ceiling Guardrails

* **Literalism Ceiling Rule:** Treat input specifications as an absolute structural ceiling. You are permitted to infer local glue logic mandatory for compilation (e.g., pipeline registers for a 3-stage reset sync chain), but you are **strictly forbidden** from inventing unlisted features (e.g., assuming automated parity checks or caching structures if they are not explicitly drawn).
* **Toolchain Calibration:** Constrain the generated hardware description to match the target compiler tools specified in the prompt deliverables (e.g., standard IEEE 1364-2005 `iverilog`). Do not inject advanced features (e.g., SystemVerilog Interfaces or Assertions) that break execution on the declared target platform.
* **Content Relevance Gating:** Completely drop non-hardware structural content. Ignore JavaScript animation handles, custom CSS presentation rules, scroll tracking functions, and template boilerplate hidden in UI navigation objects.

---

### 4. Hardware Safety & Integrity Guardrails

* **Clock & Reset Sinking Protection:** Never route structural system clocks or global reset nets through combinational logic arrays (e.g., standard AND gating) unless an explicit gating module or mux primitive is physically drawn as an SVG shape element.
* **Signal Suffix Enforcement:** Enforce polarities strictly against signal naming trends. Identifiers ending in `_n` or labeled with a clear overbar translate to low-asserted ports (`active-low`). Identifiers without suffixes map to high-asserted logic (`active-high`).
* **Infinite FSM Lockout Check:** Trace every exit path for all parsed finite state machine nodes. If an input combination enables entry into an active operational state but lacks a definitive timeout loop or transition path back to safe standby when hardware blocks freeze, issue an immediate hardware hazard warning.
* **Implicit Bus Gating:** If global system controls (e.g., `sys_rst_n`) are shown driving a top-level subsystem node, automatically propagate those interface connections down to the underlying sub-modules, even if isolated individual sub-diagrams drop the port label.

---

### 5. Summary Parsing Operational Heuristic

> **Parse textual prose for system execution rules; parse structured tables for boundary parameters; parse graphical vectors for topology/connectivity; parse embedded labels for hardware constraints. Maintain zero-loss parity between the input source text, visual SVGs, and the extracted logical netlist.**
