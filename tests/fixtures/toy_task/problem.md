## Toy Task for Testing

This is a toy task for testing the FaultEvolve evolution loop.

### Objective

Generate a Python program that produces predictions with a high score.

### Scoring

Score is deterministic based on code content:
- Base score from code hash: 15-25
- Bonus for "lightgbm" or "lgbm": +3
- Bonus for "vendor": +2
- Bonus for "trend" or "diff": +1.5
- Bonus for "threshold": +1
- Maximum score: 35

### Constraints

- No subprocess
- No path climbing
- No directory listing
