# app/config/policy_flags.py
# Phase 67-72 — Enterprise policy readiness flags (dark / internal)
# Contract-first: keys must align with frontend FeatureFlagKey union.

ENTERPRISE_FLAGS = {
    'enterprise_mode': False,
    'policy_enforcement': False,
    'white_label': False,
    'evidence_mapping': False,
}
