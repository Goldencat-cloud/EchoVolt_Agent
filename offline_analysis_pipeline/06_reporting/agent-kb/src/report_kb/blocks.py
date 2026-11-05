"""Block-type registry.

Every content block in configs/content.json is rendered by a renderer registered
here; adding a new block type = one method on Renderer + one entry in BLOCKS.
This is the pluggable layer of the report: template.html defines what a block
looks like, this registry defines how a block is built.
"""

BLOCKS = {
    "para": "_b_para",            # body paragraph (supports \n\n split)
    "note": "_b_note",            # italic caliber/reading hint
    "figure": "_b_figure",        # inline svg + caption
    "tabs": "_b_tabs",            # tabbed figure group
    "table": "_b_table",          # named generated table
    "details": "_b_details",      # collapsible region
    "cases": "_b_cases",          # case-card gallery with filter
    "recommendations": "_b_recs", # prioritized recommendation cards
    "conclusion": "_b_conclusion",# section-closing takeaway box
}
