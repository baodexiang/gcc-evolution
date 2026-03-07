"""Canonical v5.325 8-layer tier manifest for gcc-evo."""
from __future__ import annotations

LAYER_TIER_MATRIX = {
    'UI': {
        'name': 'Setup Dashboard',
        'free': ['gcc_evolution/free/ui'],
        'paid': [],
        'note': 'Configuration, connector setup, state monitoring, access visibility.',
    },
    'L0': {
        'name': 'Input Source Math Layer',
        'free': ['gcc_evolution/free/l0 (Phase 1 + L0 session gate)'],
        'paid': ['gcc_evolution/paid/l0 (Phase 2-4)'],
        'note': 'Phase 1 is free. Phase 2-4 are paid as required by v5.300.',
    },
    'L1': {
        'name': 'Memory',
        'free': ['gcc_evolution/free/l1'],
        'paid': ['gcc_evolution/paid/l1'],
        'note': 'Base memory is free, full memory stack is paid.',
    },
    'L2': {
        'name': 'Retrieval',
        'free': ['gcc_evolution/free/l2'],
        'paid': ['gcc_evolution/paid/l2'],
        'note': 'Base retrieval is free, quality-weighted/full retrieval is paid.',
    },
    'L3': {
        'name': 'Distillation',
        'free': ['gcc_evolution/free/l3'],
        'paid': ['gcc_evolution/paid/l3'],
        'note': 'Base distillation is free, advanced distillation is paid.',
    },
    'L4': {
        'name': 'Decision Evolution Engine',
        'free': [],
        'paid': ['gcc_evolution/paid/l4'],
        'note': 'Canonical paid-only layer in v5.300.',
    },
    'L5': {
        'name': 'Orchestration',
        'free': ['gcc_evolution/free/l5'],
        'paid': ['gcc_evolution/paid/l5'],
        'note': 'Base orchestration is free, advanced orchestration is paid.',
    },
    'DA': {
        'name': 'Direction Anchor',
        'free': [],
        'paid': ['gcc_evolution/paid/da'],
        'note': 'Canonical constitutional gate for paid tier.',
    },
}


def canonical_layers() -> list[str]:
    return ['UI', 'L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'DA']
