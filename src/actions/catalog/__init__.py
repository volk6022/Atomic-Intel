"""Supply-side catalog scrapers (competition analysis).

Promoted from ``experiment_monitoring/experiment-kwork`` and ``experiment-fl``:
the kwork gig catalog + seller profiles, and the fl.ru freelancer catalog. Unlike
the demand-side monitor these page deep through a category behind an anti-bot
(kwork/QRATOR, fl/DDoS-Guard), so they use the throttled, block-aware
``catalog_request`` helper rather than the plain hybrid fetch.
"""
