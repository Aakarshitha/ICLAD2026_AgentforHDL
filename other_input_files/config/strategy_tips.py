# NXP ICLAD 2026 — Verification & Agentic Strategy Rules
# This configuration file organizes strategy tips by benchmark difficulty and target IP modules.

STRATEGY_TIPS = {
    "easy": {
        "ahb_apb_bridge": (
            "Focus on getting the AHB-to-APB bridge timing right (SETUP then ENABLE phase)."
        ),
        "apb_fabric": (
            "The APB fabric must correctly decode 4KB address windows."
        ),
        "watchdog": (
            "Watchdog requires the 2-step unlock sequence (magic key = 0xABCD1234)."
        ),
        "irq_aggregator": (
            "IRQ aggregator polarity: irq_in = irq_src XOR ~polarity."
        )
    },
    "medium": {
        # Placeholders for upcoming medium-level modules and tips
    },
    "hard": {
        # Placeholders for upcoming hard-level modules and tips
    }
}
