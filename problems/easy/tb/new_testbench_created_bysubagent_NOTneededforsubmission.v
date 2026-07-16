`timescale 1ns / 1ps

// =============================================================================
// NXP ICLAD 2026 — EASY Problem: Secure Peripheral Subsystem
// Testbench Skeleton (provided to participants)
//
// INSTRUCTIONS:
//   1. Study the architecture diagram in docs/architecture.md
//   2. Read the IP descriptions in docs/ip_descriptions.md
//   3. Use the RTL generation library to produce each IP Verilog file
//   4. Implement soc_top.v that instantiates and connects all IPs
//   5. Your design must compile and simulate with:
//        iverilog -g2005 -o sim your_rtl/*.v this_tb.v
//        vvp sim
//   6. The evaluator will replace this skeleton with the hidden golden TB
//      and score your design against all test categories.
//
// PORT CONTRACT (DO NOT MODIFY this module's interface):
//   Your top-level module MUST be named:  secure_periph_soc
//   with exactly the port list shown in the DUT instantiation below.
// =============================================================================
`timescale 1ns/1ps

module tb_top;

    // =========================================================================
    // TEST SUITE CONTROL FLAGS (Fixes "Unable to bind wire/reg/memory" errors)
    // =========================================================================
    reg        RUN_ALL             = 1; // Set to 1 to run all tests, 0 to run selectively

    // Category Skip Flags (0 = Run this category, 1 = Skip)
    reg        skip_basic_rw             = 0;
    reg        skip_uart_tx              = 0;
    reg        skip_gpio_irq             = 0;
    reg        skip_timer                = 0;
    reg        skip_watchdog             = 0;
    reg        skip_privilege            = 0;
    reg        skip_irq_aggregator       = 0;
    reg        skip_reset_sync           = 0;

    // Individual Test Run Flags (1 = Run, 0 = Do Not Run)
    // CATEGORY: BASIC RW
    reg        run_T101                   = 1;
    reg        run_T102                   = 1;
    reg        run_T103                   = 1;
    reg        run_T104                   = 1;
    // CATEGORY: UART TX
    reg        run_T201                   = 1;
    reg        run_T202                   = 1;
    reg        run_T203                   = 1;
    // CATEGORY: GPIO IRQ
    reg        run_T301                   = 1;
    reg        run_T302                   = 1;
    reg        run_T303                   = 1;
    // CATEGORY: TIMER
    reg        run_T401                   = 1;
    reg        run_T402                   = 1;
    reg        run_T403                   = 1;
    // CATEGORY: WATCHDOG
    reg        run_T501                   = 1;
    reg        run_T502                   = 1;
    // CATEGORY: PRIVILEGE
    reg        run_T601                   = 1;
    reg        run_T602                   = 1;
    reg        run_T603                   = 1;
    // CATEGORY: IRQ AGGREGATOR
    reg        run_T701                   = 1;
    reg        run_T702                   = 1;
    // CATEGORY: RESET SYNC
    reg        run_T801                   = 1;
    reg        run_T802                   = 1;

    // Baseline Simulation Registers
    reg [31:0]  rd;
    reg [1:0]   rs;
    integer     local_errors;
    integer     error_count         = 0;



    // ── DUT connections ───────────────────────────────────────────────────
    reg         clk;
    reg         por_n;

    // AHB-Lite CPU master port
    reg  [31:0] cpu_haddr;
    reg  [1:0]  cpu_htrans;
    reg         cpu_hwrite;
    reg  [2:0]  cpu_hsize;
    reg  [2:0]  cpu_hburst;
    reg  [2:0]  cpu_hprot;
    reg  [31:0] cpu_hwdata;
    wire [31:0] cpu_hrdata;
    wire        cpu_hready;
    wire [1:0]  cpu_hresp;     // 00=OKAY  01=ERROR

    // GPIO
    reg  [31:0] gpio_in;
    wire [31:0] gpio_out;
    wire [31:0] gpio_oe;       // output enable, 1=output

    // UART
    wire        uart_tx;
    reg         uart_rx;
    reg         uart_cts_n;    // clear-to-send (active low)
    wire        uart_rts_n;    // request-to-send (active low)

    // PWM (from timer output compare)
    wire        pwm0;
    wire        pwm1;

    // Interrupt to CPU
    wire        cpu_irq;
    wire [2:0]  cpu_irq_id;    // vector ID of highest-priority pending IRQ

    // Watchdog reset output
    wire        wdt_rst_req;   // pulses when WDT stage-2 expires

    // ── DUT instantiation ─────────────────────────────────────────────────
    // Implement this module in your RTL files.
    secure_periph_soc dut (
        .clk         (clk),
        .por_n       (por_n),
        .cpu_haddr   (cpu_haddr),
        .cpu_htrans  (cpu_htrans),
        .cpu_hwrite  (cpu_hwrite),
        .cpu_hsize   (cpu_hsize),
        .cpu_hburst  (cpu_hburst),
        .cpu_hprot   (cpu_hprot),
        .cpu_hwdata  (cpu_hwdata),
        .cpu_hrdata  (cpu_hrdata),
        .cpu_hready  (cpu_hready),
        .cpu_hresp   (cpu_hresp),
        .gpio_in     (gpio_in),
        .gpio_out    (gpio_out),
        .gpio_oe     (gpio_oe),
        .uart_tx     (uart_tx),
        .uart_rx     (uart_rx),
        .uart_cts_n  (uart_cts_n),
        .uart_rts_n  (uart_rts_n),
        .pwm0        (pwm0),
        .pwm1        (pwm1),
        .cpu_irq     (cpu_irq),
        .cpu_irq_id  (cpu_irq_id),
        .wdt_rst_req (wdt_rst_req)
    );

    // ── Clock ─────────────────────────────────────────────────────────────
    initial clk = 0;
    always  #5 clk = ~clk;   // 100 MHz

    // ── Reset ─────────────────────────────────────────────────────────────
    initial begin
        por_n      = 0;
        cpu_htrans = 2'b00;  // IDLE
        cpu_hwrite = 0;
        cpu_haddr  = 0;
        cpu_hwdata = 0;
        cpu_hprot  = 3'b001; // privileged data access
        cpu_hsize  = 3'b010; // word
        cpu_hburst = 3'b000; // SINGLE
        gpio_in    = 0;
        uart_rx    = 1;      // UART idle = high
        uart_cts_n = 0;      // CTS asserted

        repeat(20) @(posedge clk);
        por_n = 1;
        repeat(5)  @(posedge clk);

        // ── YOUR SANITY CHECKS HERE ────────────────────────────────────────
        // Write a basic AHB transfer to verify your bus fabric works:
        // --- T101: Basic Sanity Test ---
        if (!skip_basic_rw && (RUN_ALL || run_T101)) begin
            local_errors = 0;
            $display("[SUITE] Starting T101: GPIO DIR RW...");
            ahb_write(32'h0000_1008, 32'hA5A5_5A5A, 3'b001);
            ahb_read(32'h0000_1008, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (rd !== 32'hA5A5_5A5A) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T101");
            end else begin
                $display("[FAIL] T101");
            end
        end

        // --- T102: Basic Sanity Test ---
        if (!skip_basic_rw && (RUN_ALL || run_T102)) begin
            local_errors = 0;
            $display("[SUITE] Starting T102: TIMER LOAD RW...");
            ahb_write(32'h0000_2000, 32'h1234_5678, 3'b001);
            ahb_read(32'h0000_2000, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (rd !== 32'h1234_5678) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T102");
            end else begin
                $display("[FAIL] T102");
            end
        end

        // --- T103: Basic Sanity Test ---
        if (!skip_basic_rw && (RUN_ALL || run_T103)) begin
            local_errors = 0;
            $display("[SUITE] Starting T103: IRQA EN RW...");
            ahb_write(32'h0000_4008, 32'h0000_00FF, 3'b001);
            ahb_read(32'h0000_4008, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (rd !== 32'h0000_00FF) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T103");
            end else begin
                $display("[FAIL] T103");
            end
        end

        // --- T104: Basic Sanity Test ---
        if (!skip_basic_rw && (RUN_ALL || run_T104)) begin
            local_errors = 0;
            $display("[SUITE] Starting T104: UART CTRL RW...");
            ahb_write(32'h0000_000C, 32'h0000_0100, 3'b001);
            ahb_read(32'h0000_000C, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (rd !== 32'h0000_0100) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T104");
            end else begin
                $display("[FAIL] T104");
            end
        end

        // --- T201: UART TX Test ---
        if (!skip_uart_tx && (RUN_ALL || run_T201)) begin
            local_errors = 0;
            $display("[SUITE] Starting T201: UART TXDATA Write...");
            ahb_write(32'h0000_0000, 32'h0000_0055, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T201");
            end else begin
                $display("[FAIL] T201");
            end
        end

        // --- T202: UART TX Test ---
        if (!skip_uart_tx && (RUN_ALL || run_T202)) begin
            local_errors = 0;
            $display("[SUITE] Starting T202: UART STATUS Read...");
            ahb_read(32'h0000_0008, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T202");
            end else begin
                $display("[FAIL] T202");
            end
        end

        // --- T203: UART TX Test ---
        if (!skip_uart_tx && (RUN_ALL || run_T203)) begin
            local_errors = 0;
            $display("[SUITE] Starting T203: UART CTRL Enable TX...");
            ahb_write(32'h0000_000C, 32'h0000_0001, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T203");
            end else begin
                $display("[FAIL] T203");
            end
        end

        // --- T301: GPIO IRQ Test ---
        if (!skip_gpio_irq && (RUN_ALL || run_T301)) begin
            local_errors = 0;
            $display("[SUITE] Starting T301: GPIO DIR Input...");
            ahb_write(32'h0000_1008, 32'h0000_0000, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T301");
            end else begin
                $display("[FAIL] T301");
            end
        end

        // --- T302: GPIO IRQ Test ---
        if (!skip_gpio_irq && (RUN_ALL || run_T302)) begin
            local_errors = 0;
            $display("[SUITE] Starting T302: GPIO IRQ_EN...");
            ahb_write(32'h0000_1014, 32'hFFFF_FFFF, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T302");
            end else begin
                $display("[FAIL] T302");
            end
        end

        // --- T303: GPIO IRQ Test ---
        if (!skip_gpio_irq && (RUN_ALL || run_T303)) begin
            local_errors = 0;
            $display("[SUITE] Starting T303: GPIO IRQ_EDGE...");
            ahb_write(32'h0000_1018, 32'hFFFF_FFFF, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T303");
            end else begin
                $display("[FAIL] T303");
            end
        end

        // --- T401: Timer Test ---
        if (!skip_timer && (RUN_ALL || run_T401)) begin
            local_errors = 0;
            $display("[SUITE] Starting T401: TIMER CH0 LOAD...");
            ahb_write(32'h0000_2000, 32'h0000_0100, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T401");
            end else begin
                $display("[FAIL] T401");
            end
        end

        // --- T402: Timer Test ---
        if (!skip_timer && (RUN_ALL || run_T402)) begin
            local_errors = 0;
            $display("[SUITE] Starting T402: TIMER CH0 CTRL...");
            ahb_write(32'h0000_2008, 32'h0000_0001, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T402");
            end else begin
                $display("[FAIL] T402");
            end
        end

        // --- T403: Timer Test ---
        if (!skip_timer && (RUN_ALL || run_T403)) begin
            local_errors = 0;
            $display("[SUITE] Starting T403: TIMER CH0 VALUE...");
            ahb_read(32'h0000_2004, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T403");
            end else begin
                $display("[FAIL] T403");
            end
        end

        // --- T501: Watchdog Test ---
        if (!skip_watchdog && (RUN_ALL || run_T501)) begin
            local_errors = 0;
            $display("[SUITE] Starting T501: WDT Unlock...");
            ahb_write(32'h0000_3014, 32'hABCD_1234, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T501");
            end else begin
                $display("[FAIL] T501");
            end
        end

        // --- T502: Watchdog Test ---
        if (!skip_watchdog && (RUN_ALL || run_T502)) begin
            local_errors = 0;
            $display("[SUITE] Starting T502: WDT Config...");
            ahb_write(32'h0000_3000, 32'h0000_00FF, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T502");
            end else begin
                $display("[FAIL] T502");
            end
        end

        // --- T601: Privilege Test ---
        if (!skip_privilege && (RUN_ALL || run_T601)) begin
            local_errors = 0;
            $display("[SUITE] Starting T601: Unprivileged WDT Write...");
            ahb_write(32'h0000_3014, 32'hABCD_1234, 3'b000);
            if (cpu_hresp !== 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T601");
            end else begin
                $display("[FAIL] T601");
            end
        end

        // --- T602: Privilege Test ---
        if (!skip_privilege && (RUN_ALL || run_T602)) begin
            local_errors = 0;
            $display("[SUITE] Starting T602: Privileged WDT Write...");
            ahb_write(32'h0000_3014, 32'hABCD_1234, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T602");
            end else begin
                $display("[FAIL] T602");
            end
        end

        // --- T603: Privilege Test ---
        if (!skip_privilege && (RUN_ALL || run_T603)) begin
            local_errors = 0;
            $display("[SUITE] Starting T603: Unmapped Address Access...");
            ahb_write(32'h0000_5000, 32'h0000_0000, 3'b001);
            if (cpu_hresp !== 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T603");
            end else begin
                $display("[FAIL] T603");
            end
        end

        // --- T701: IRQ Aggregator Test ---
        if (!skip_irq_aggregator && (RUN_ALL || run_T701)) begin
            local_errors = 0;
            $display("[SUITE] Starting T701: IRQA Polarity XOR...");
            ahb_write(32'h0000_4010, 32'h0000_0000, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T701");
            end else begin
                $display("[FAIL] T701");
            end
        end

        // --- T702: IRQ Aggregator Test ---
        if (!skip_irq_aggregator && (RUN_ALL || run_T702)) begin
            local_errors = 0;
            $display("[SUITE] Starting T702: IRQA RAW Read...");
            ahb_read(32'h0000_4000, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T702");
            end else begin
                $display("[FAIL] T702");
            end
        end

        // --- T801: Reset Sync Test ---
        if (!skip_reset_sync && (RUN_ALL || run_T801)) begin
            local_errors = 0;
            $display("[SUITE] Starting T801: WDT Reset Trigger...");
            ahb_write(32'h0000_3014, 32'hABCD_1234, 3'b001);
            ahb_write(32'h0000_3004, 32'h0000_0001, 3'b001);
            ahb_write(32'h0000_300C, 32'h0000_0005, 3'b001);
            if (cpu_hresp === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T801");
            end else begin
                $display("[FAIL] T801");
            end
        end

        // --- T802: Reset Sync Test ---
        if (!skip_reset_sync && (RUN_ALL || run_T802)) begin
            local_errors = 0;
            $display("[SUITE] Starting T802: Reset Sync Check...");
            ahb_read(32'h0000_1008, 3'b001, rd, rs);
            if (rs === 2'b01) begin
                local_errors = local_errors + 1;
            end
            if (local_errors == 0) begin
                $display("[PASS] T802");
            end else begin
                $display("[FAIL] T802");
            end
        end
        //   ahb_write(32'h0000_1004, 32'hDEADC0DE, 3'b001);  // GPIO DATA_OUT
        //   ahb_read (32'h0000_1004, 3'b001, rd, rs);
        //   if (rd === 32'hDEADC0DE) $display("GPIO write-readback PASS");
        //   else $display("GPIO write-readback FAIL: got %h", rd);

        $display("Skeleton TB: basic sanity only — add your own checks here.");
        $finish;
    end

    // ── AHB master helper tasks ───────────────────────────────────────────
    // Address map:
    //   UART     : 0x0000_0000 – 0x0000_0FFF
    //   GPIO     : 0x0000_1000 – 0x0000_1FFF
    //   TIMER    : 0x0000_2000 – 0x0000_2FFF
    //   WATCHDOG : 0x0000_3000 – 0x0000_3FFF  (privileged access only)
    //   IRQ_AGG  : 0x0000_4000 – 0x0000_4FFF

    task ahb_write;
   
        input [31:0] addr, data;
        input [2:0]  prot;
        begin
            // Drive on negedge; poll hready with #1 for NBA visibility
            @(negedge clk);
            cpu_haddr=addr; cpu_htrans=2'b10; cpu_hwrite=1;
            cpu_hprot=prot; cpu_hwdata=data;
            cpu_hsize=3'b010; cpu_hburst=0;
            @(posedge clk); #1;
            while (!cpu_hready) begin @(posedge clk); #1; end
            @(negedge clk); cpu_htrans=2'b00; cpu_hwrite=0;
            @(posedge clk); #1;
        end
    
    endtask

    task ahb_read;

        input  [31:0] addr;
        input  [2:0]  prot;
        output [31:0] rdata;
        output [1:0]  resp;
        begin
            @(negedge clk);
            cpu_haddr=addr; cpu_htrans=2'b10; cpu_hwrite=0;
            cpu_hprot=prot; cpu_hsize=3'b010; cpu_hburst=0;
            @(posedge clk); #1;
            while (!cpu_hready) begin @(posedge clk); #1; end
            rdata = cpu_hrdata; resp = cpu_hresp;
            @(negedge clk); cpu_htrans=2'b00;
            @(posedge clk); #1;
        end
    
    endtask

    // ── Timeout guard ────────────────────────────────────────────────────
    initial begin
        #5_000_000;
        $display("[TIMEOUT] 5ms simulation limit reached");
        $finish;
    end

endmodule
