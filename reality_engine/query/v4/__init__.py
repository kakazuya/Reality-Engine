"""Query layer v4 — pilot builds (§H.2, §A.8, §A.9, §B.3, §E.1).

Builders here read the held pilot stores read-only and write their own database
files; nothing in this package answers a question yet (that is WP2a's fact view
and WP4's executor).

    build_vocab         measured surface layer + declared label layer + promotion queue
    build_claim         typed claims from concall_facts.cc_items (label ids + facets)
    build_own_estimate  the trend estimate and its measured in-line band, PIT-replayable
    build_edge_schema   the four discovery-layer tables (schema only)

The vocab tables live in their own file (attach it as ``vocab``); the claim and
estimate tables live in the v4 database.
"""
