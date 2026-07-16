// FILE: secure_periph_soc.v

module secure_periph_soc (
    input  wire        clk,
    input  wire        por_n,
    
    // AHB-Lite CPU master port
    input  wire [31:0] cpu_haddr,
    input  wire [1:0]  cpu_htrans,
    input  wire        cpu_hwrite,
    input  wire [2:0]  cpu_hsize,
    input  wire [2:0]  cpu_hburst,
    input  wire [2:0]  cpu_hprot,
    input  wire [31:0] cpu_hwdata,
    output wire [31:0] cpu_hrdata,
    output wire        cpu_hready,
    output wire [1:0]  cpu_hresp,
    
    // GPIO
    input  wire [31:0] gpio_in,
    output wire [31:0] gpio_out,
    output wire [31:0] gpio_oe,
    
    // UART
    output wire        uart_tx,
    input  wire        uart_rx,
    input  wire        uart_cts_n,
    output wire        uart_rts_n,
    
    // PWM
    output wire        pwm0,
    output wire        pwm1,
    
    // Interrupts
    output wire        cpu_irq,
    output wire [2:0]  cpu_irq_id,
    
    // Watchdog
    output wire        wdt_rst_req
);

    // -------------------------------------------------------------------------
    // Internal Wire Declarations
    // -------------------------------------------------------------------------
    
    // Reset
    wire sys_rst_n;
    wire wdt_rst_n = ~wdt_rst_req;
    
    // APB Master Bus (from AHB-APB Bridge to Fabric)
    wire        apb_psel;
    wire        apb_penable;
    wire        apb_pwrite;
    wire [31:0] apb_paddr;
    wire [31:0] apb_pwdata;
    wire [2:0]  apb_pprot;
    wire [31:0] apb_prdata;
    wire        apb_pready;
    wire        apb_pslverr;
    
    // APB Slave 0: UART
    wire        s0_psel;
    wire        s0_penable;
    wire        s0_pwrite;
    wire [11:0] s0_paddr;
    wire [31:0] s0_pwdata;
    wire [31:0] s0_prdata;
    wire        s0_pready;
    wire        s0_pslverr;
    wire        uart_irq;
    
    // APB Slave 1: GPIO
    wire        s1_psel;
    wire        s1_penable;
    wire        s1_pwrite;
    wire [11:0] s1_paddr;
    wire [31:0] s1_pwdata;
    wire [31:0] s1_prdata;
    wire        s1_pready;
    wire        s1_pslverr;
    wire        gpio_irq;
    wire [63:0] gpio_alt_func;
    
    // APB Slave 2: Timer
    wire        s2_psel;
    wire        s2_penable;
    wire        s2_pwrite;
    wire [11:0] s2_paddr;
    wire [31:0] s2_pwdata;
    wire [31:0] s2_prdata;
    wire        s2_pready;
    wire        s2_pslverr;
    wire        timer_irq;
    
    // APB Slave 3: Watchdog
    wire        s3_psel;
    wire        s3_penable;
    wire        s3_pwrite;
    wire [11:0] s3_paddr;
    wire [31:0] s3_pwdata;
    wire [31:0] s3_prdata;
    wire        s3_pready;
    wire        s3_pslverr;
    wire        wdt_irq;
    
    // APB Slave 4: IRQ Aggregator
    wire        s4_psel;
    wire        s4_penable;
    wire        s4_pwrite;
    wire [11:0] s4_paddr;
    wire [31:0] s4_pwdata;
    wire [31:0] s4_prdata;
    wire        s4_pready;
    wire        s4_pslverr;
    
    // -------------------------------------------------------------------------
    // Sub-IP Instantiations
    // -------------------------------------------------------------------------
    
    // Reset Synchronizer
    reset_sync #(
        .STAGES(3)
    ) u_reset_sync (
        .clk       (clk),
        .por_n     (por_n),
        .wdt_rst_n (wdt_rst_n),
        .sys_rst_n (sys_rst_n)
    );
    
    // AHB to APB Bridge
    ahb_to_apb_bridge u_ahb_to_apb_bridge (
        .hclk       (clk),
        .hresetn    (sys_rst_n),
        .haddr      (cpu_haddr),
        .htrans     (cpu_htrans),
        .hwrite     (cpu_hwrite),
        .hsize      (cpu_hsize),
        .hburst     (cpu_hburst),
        .hprot      (cpu_hprot),
        .hwdata     (cpu_hwdata),
        .hsel       (1'b1),
        .hready_in  (1'b1),
        .hrdata     (cpu_hrdata),
        .hready_out (cpu_hready),
        .hresp      (cpu_hresp),
        .psel       (apb_psel),
        .penable    (apb_penable),
        .pwrite     (apb_pwrite),
        .paddr      (apb_paddr),
        .pwdata     (apb_pwdata),
        .pprot      (apb_pprot),
        .prdata     (apb_prdata),
        .pready     (apb_pready),
        .pslverr    (apb_pslverr)
    );
    
    // APB Fabric Decode
    apb_fabric5 #(
        .TIMEOUT_CYC(16)
    ) u_apb_fabric5 (
        .pclk       (clk),
        .presetn    (sys_rst_n),
        .m_psel     (apb_psel),
        .m_penable  (apb_penable),
        .m_pwrite   (apb_pwrite),
        .m_paddr    (apb_paddr),
        .m_pwdata   (apb_pwdata),
        .m_pprot    (apb_pprot),
        .m_prdata   (apb_prdata),
        .m_pready   (apb_pready),
        .m_pslverr  (apb_pslverr),
        
        .s0_psel    (s0_psel),
        .s0_penable (s0_penable),
        .s0_pwrite  (s0_pwrite),
        .s0_paddr   (s0_paddr),
        .s0_pwdata  (s0_pwdata),
        .s0_prdata  (s0_prdata),
        .s0_pready  (s0_pready),
        .s0_pslverr (s0_pslverr),
        
        .s1_psel    (s1_psel),
        .s1_penable (s1_penable),
        .s1_pwrite  (s1_pwrite),
        .s1_paddr   (s1_paddr),
        .s1_pwdata  (s1_pwdata),
        .s1_prdata  (s1_prdata),
        .s1_pready  (s1_pready),
        .s1_pslverr (s1_pslverr),
        
        .s2_psel    (s2_psel),
        .s2_penable (s2_penable),
        .s2_pwrite  (s2_pwrite),
        .s2_paddr   (s2_paddr),
        .s2_pwdata  (s2_pwdata),
        .s2_prdata  (s2_prdata),
        .s2_pready  (s2_pready),
        .s2_pslverr (s2_pslverr),
        
        .s3_psel    (s3_psel),
        .s3_penable (s3_penable),
        .s3_pwrite  (s3_pwrite),
        .s3_paddr   (s3_paddr),
        .s3_pwdata  (s3_pwdata),
        .s3_prdata  (s3_prdata),
        .s3_pready  (s3_pready),
        .s3_pslverr (s3_pslverr),
        
        .s4_psel    (s4_psel),
        .s4_penable (s4_penable),
        .s4_pwrite  (s4_pwrite),
        .s4_paddr   (s4_paddr),
        .s4_pwdata  (s4_pwdata),
        .s4_prdata  (s4_prdata),
        .s4_pready  (s4_pready),
        .s4_pslverr (s4_pslverr)
    );
    
    // APB UART
    apb_uart #(
        .FIFO_DEPTH(16),
        .DEFAULT_DIV(0)
    ) u_apb_uart (
        .pclk       (clk),
        .presetn    (sys_rst_n),
        .psel       (s0_psel),
        .penable    (s0_penable),
        .pwrite     (s0_pwrite),
        .paddr      (s0_paddr),
        .pwdata     (s0_pwdata),
        .prdata     (s0_prdata),
        .pready     (s0_pready),
        .pslverr    (s0_pslverr),
        .uart_tx    (uart_tx),
        .uart_rx    (uart_rx),
        .cts_n      (uart_cts_n),
        .rts_n      (uart_rts_n),
        .irq        (uart_irq)
    );
    
    // APB GPIO
    apb_gpio #(
        .GPIO_WIDTH(32),
        .DBS(3)
    ) u_apb_gpio (
        .pclk       (clk),
        .presetn    (sys_rst_n),
        .psel       (s1_psel),
        .penable    (s1_penable),
        .pwrite     (s1_pwrite),
        .paddr      (s1_paddr),
        .pwdata     (s1_pwdata),
        .prdata     (s1_prdata),
        .pready     (s1_pready),
        .pslverr    (s1_pslverr),
        .gpio_in    (gpio_in),
        .gpio_out   (gpio_out),
        .gpio_oe    (gpio_oe),
        .alt_func   (gpio_alt_func),
        .irq        (gpio_irq)
    );
    
    // APB Timer
    apb_timer #(
        .CHANNELS(2),
        .WIDTH(32)
    ) u_apb_timer (
        .pclk       (clk),
        .presetn    (sys_rst_n),
        .psel       (s2_psel),
        .penable    (s2_penable),
        .pwrite     (s2_pwrite),
        .paddr      (s2_paddr),
        .pwdata     (s2_pwdata),
        .prdata     (s2_prdata),
        .pready     (s2_pready),
        .pslverr    (s2_pslverr),
        .pwm0       (pwm0),
        .pwm1       (pwm1),
        .irq        (timer_irq)
    );
    
    // APB Watchdog
    apb_watchdog #(
        .DEFAULT_LOAD1(32'h0001_0000),
        .DEFAULT_LOAD2(32'h0000_8000)
    ) u_apb_watchdog (
        .pclk       (clk),
        .presetn    (sys_rst_n),
        .psel       (s3_psel),
        .penable    (s3_penable),
        .pwrite     (s3_pwrite),
        .paddr      (s3_paddr),
        .pwdata     (s3_pwdata),
        .prdata     (s3_prdata),
        .pready     (s3_pready),
        .pslverr    (s3_pslverr),
        .wdt_irq    (wdt_irq),
        .wdt_rst_req(wdt_rst_req)
    );
    
    // IRQ Aggregator
    irq_aggregator u_irq_aggregator (
        .pclk       (clk),
        .presetn    (sys_rst_n),
        .psel       (s4_psel),
        .penable    (s4_penable),
        .pwrite     (s4_pwrite),
        .paddr      (s4_paddr),
        .pwdata     (s4_pwdata),
        .prdata     (s4_prdata),
        .pready     (s4_pready),
        .pslverr    (s4_pslverr),
        .irq_src    ({4'b0000, wdt_irq, timer_irq, gpio_irq, uart_irq}),
        .cpu_irq    (cpu_irq),
        .cpu_irq_id (cpu_irq_id)
    );

endmodule
