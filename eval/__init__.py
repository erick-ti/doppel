"""Day-7 evaluation harness (library, not part of the app package).

Drives the *real* pipeline (`aggregate` → `run_pipeline(execution_mode="job")`) over benchmark seeds
against a live Postgres + CLAP, then reports coverage / score-distribution / audio-vs-cultural
ablation / latency metrics. See `eval/harness.py`; reports land in the gitignored `eval/reports/`.
"""
