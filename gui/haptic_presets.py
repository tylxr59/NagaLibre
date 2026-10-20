"""Names traced through Razer's enum attributes and English UI resources.

Descriptions are independently worded summaries. Protocol provenance and exact
resource keys are documented in inspection/HAPTIC_WHEEL.md.
"""
PRESET_NAMES = {
    0x81: "Standard",
    0x82: "Distinct",
    0x83: "Ultra-fine",
    0x84: "Adaptive",
    0x85: "Smooth Scroll",
    0x86: "Custom",
}
PRESET_DESCRIPTIONS = {
    0x81: "Normal, default wheel movement.",
    0x82: "Firm, clearly separated ticks for precise selections.",
    0x83: "Softer, smoother movement with many small steps for rapid inputs.",
    0x84: "Scrolling becomes smoother as you turn the wheel faster; try slow and fast turns.",
    0x85: "Smooth movement with little tactile resistance, intended for browsing.",
    0x86: "Your own resistance, steps and haptic curve settings.",
}
BUILTIN_PRESETS = tuple(stage for stage in PRESET_NAMES if stage != 0x86)
