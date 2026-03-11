from gcc_evolution.L3_distillation.distiller import ExperienceDistiller


def test_distill_blocks_overconfident_weak_summary_pattern():
    distiller = ExperienceDistiller(min_confidence=0.7)
    distiller.experience_log = [
        {
            "conditions": {"task": "alpha"},
            "outcome": {"success": True, "action": "x"},
        },
        {
            "conditions": {"task": "alpha"},
            "outcome": {"success": True, "action": "x"},
        },
    ]

    patterns = distiller._extract_patterns()
    assert patterns
    patterns[0]["summary"] = "too short"
    patterns[0]["confidence"] = 0.99

    assert distiller._passes_hallucination_gate(patterns[0]) is False
    assert distiller.rejected_patterns


def test_distill_keeps_valid_pattern():
    distiller = ExperienceDistiller(min_confidence=0.7)
    distiller.add_experience(
        {
            "conditions": {"task": "beta"},
            "outcome": {"success": True, "action": "baseline"},
        }
    )
    distiller.add_experience(
        {
            "conditions": {"task": "beta"},
            "outcome": {"success": True, "action": "baseline"},
        }
    )

    cards = distiller.distill()

    assert len(cards) == 1
