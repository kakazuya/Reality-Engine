"""Query layer v4 (WP4): one executor, the typed answer contract, the renderer.

``execute`` reads only the ``fact`` view (§B.1) plus the stored objects the design
names (``own_estimate``, ``claim``, ``edge``, ``membership``).  The renderer
turns a list of results into the four block types of §D.4.  No database is
opened by this package: the caller passes a read-only connection.
"""
