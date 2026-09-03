"""Strike ranking domain (Day 30): Best-Strike Ranking.

Deterministic, broker-neutral multi-factor strike selection on the Day-28
Opportunity foundation:

    Eligible Opportunity -> Strike Candidate Set -> Factor Evaluation
        -> Deterministic Ranking -> Explainable Ranked Strikes

A ranked strike is an evaluation/selection result -- never an order,
never an execution intent, never a risk authorization.
"""
