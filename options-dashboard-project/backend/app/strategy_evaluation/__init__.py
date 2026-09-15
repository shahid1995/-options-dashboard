"""Strategy evaluation domain (Day 31): deterministic evaluation of an
already-defined strategy candidate against supplied market/context evidence.

    Strategy Candidate -> Strategy Evaluation -> Evaluation Result

The evaluator answers how a strategy behaves and how suitable it is under
the supplied evidence.  It never answers whether an order should be placed:
no order creation, execution intent, broker interaction, user approval,
position mutation or central-risk authorization exists here.
"""
