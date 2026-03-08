"""Canonical v5.330 8-layer tier manifest for gcc-evo."""
from __future__ import annotations

LAYER_TIER_MATRIX = {
    'UI': {
        'name': 'Setup Dashboard',
        'free': ['gcc_evolution/free/ui'],
        'paid': [],
        'note': 'Configuration, connector setup, state monitoring, access visibility.',
    },
    'L0': {
        'name': 'Foundation Governance Layer',
        'free': ['gcc_evolution/free/l0'],
        'paid': ['gcc_evolution/paid/l0 (commercial enhancement pack)'],
        'note': 'Canonical layer count treats L0 as part of the 5 free foundation layers.',
    },
    'L1': {
        'name': 'Memory',
        'free': ['gcc_evolution/free/l1'],
        'paid': ['gcc_evolution/paid/l1 (commercial enhancement pack)'],
        'note': 'Canonical layer count treats L1 as part of the 5 free foundation layers.',
    },
    'L2': {
        'name': 'Retrieval',
        'free': ['gcc_evolution/free/l2'],
        'paid': ['gcc_evolution/paid/l2 (commercial enhancement pack)'],
        'note': 'Canonical layer count treats L2 as part of the 5 free foundation layers.',
    },
    'L3': {
        'name': 'Distillation',
        'free': ['gcc_evolution/free/l3'],
        'paid': ['gcc_evolution/paid/l3 (commercial enhancement pack)'],
        'note': 'Canonical layer count treats L3 as part of the 5 free foundation layers.',
    },
    'L4': {
        'name': 'Decision Evolution Engine',
        'free': [],
        'paid': ['gcc_evolution/paid/l4'],
        'note': 'Canonical paid-only layer in v5.300.',
    },
    'L5': {
        'name': 'Orchestration',
        'free': [],
        'paid': ['gcc_evolution/paid/l5'],
        'note': 'Canonical paid-core layer in the 5-free + 3-paid release model.',
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

