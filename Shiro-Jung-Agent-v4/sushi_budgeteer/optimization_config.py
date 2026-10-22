"""Shared production settings: app/build tool and benchmark use the same values."""
FOOD_OBJECTIVE = 'budget'
DIVERSITY = True
NEAR_BUDGET_PERCENT = 95
INITIAL_SPEND_RATIO = 0.8  # Product choice requested by the user; not an optimality theorem.
MAX_FOOD_ITEMS = 60
MAX_REPEAT = 3

# Product intake floor requested by the user; not a satiety or price guarantee.
MIN_INTAKE_BUDGET_PER_PERSON = 100.0
