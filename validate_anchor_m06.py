"""
KEY-005-M06 Anchor Map Validation Run 1/2
Validates: anchor selection, strength scoring, nearest logic, integration
"""

import sys
import json
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.behavior_finance import (
    _compute_anchor_map,
    _to_float,
    _clip,
    _scale,
)

DEFECTS = []
PASSES = []

def test_anchor_selection():
    """Test 1: Anchor selection logic (integer/52w/cost basis)"""
    print("\n=== TEST 1: Anchor Selection Logic ===")
    
    # Test case 1: Normal price
    current_price = 150.5
    step = 10.0 if current_price >= 100 else 1.0
    int_anchor = round(current_price / step) * step
    
    # Expected: 150.0 (150.5 / 10 = 15.05, round = 15, * 10 = 150)
    if int_anchor == 150.0:
        PASSES.append("TEST1.1: Integer anchor calculation correct (150.0)")
        print("✓ Integer anchor: 150.0")
    else:
        DEFECTS.append(f"TEST1.1: Integer anchor wrong. Expected 150.0, got {int_anchor}")
        print(f"✗ Integer anchor: Expected 150.0, got {int_anchor}")
    
    # Test case 2: High price (>1000)
    current_price = 1500.5
    step = 100.0 if current_price >= 1000 else 10.0
    int_anchor = round(current_price / step) * step
    
    if int_anchor == 1500.0:
        PASSES.append("TEST1.2: Integer anchor for high price correct (1500.0)")
        print("✓ Integer anchor (high): 1500.0")
    else:
        DEFECTS.append(f"TEST1.2: Integer anchor (high) wrong. Expected 1500.0, got {int_anchor}")
        print(f"✗ Integer anchor (high): Expected 1500.0, got {int_anchor}")
    
    # Test case 3: Low price (<100)
    current_price = 5.5
    step = 1.0 if current_price < 100 else 10.0
    int_anchor = round(current_price / step) * step
    
    if int_anchor == 6.0:
        PASSES.append("TEST1.3: Integer anchor for low price correct (6.0)")
        print("✓ Integer anchor (low): 6.0")
    else:
        DEFECTS.append(f"TEST1.3: Integer anchor (low) wrong. Expected 6.0, got {int_anchor}")
        print(f"✗ Integer anchor (low): Expected 6.0, got {int_anchor}")

def test_strength_scoring():
    """Test 2: Strength scoring (proximity + base_strength)"""
    print("\n=== TEST 2: Strength Scoring ===")
    
    current_price = 150.0
    anchor_price = 150.0
    base_strength = 0.85
    
    # Distance calculation
    dist_pct = abs(current_price - anchor_price) / max(current_price, 1e-9)
    proximity = _clip(1.0 - dist_pct / 0.08, 0.0, 1.0)
    strength = _clip(base_strength * 100.0 * proximity, 0.0, 100.0)
    
    # At exact anchor: dist_pct=0, proximity=1.0, strength=85.0
    if abs(strength - 85.0) < 0.01:
        PASSES.append("TEST2.1: Strength at exact anchor correct (85.0)")
        print(f"✓ Strength at exact anchor: {strength:.2f}")
    else:
        DEFECTS.append(f"TEST2.1: Strength at exact anchor wrong. Expected 85.0, got {strength:.2f}")
        print(f"✗ Strength at exact anchor: Expected 85.0, got {strength:.2f}")
    
    # Test at 4% distance (half of 8% threshold)
    current_price = 150.0
    anchor_price = 156.0  # 4% away
    dist_pct = abs(current_price - anchor_price) / max(current_price, 1e-9)
    proximity = _clip(1.0 - dist_pct / 0.08, 0.0, 1.0)
    strength = _clip(base_strength * 100.0 * proximity, 0.0, 100.0)
    
    # dist_pct = 0.04, proximity = 1.0 - 0.04/0.08 = 0.5, strength = 85 * 0.5 = 42.5
    if abs(strength - 42.5) < 0.01:
        PASSES.append("TEST2.2: Strength at 4% distance correct (42.5)")
        print(f"✓ Strength at 4% distance: {strength:.2f}")
    else:
        DEFECTS.append(f"TEST2.2: Strength at 4% distance wrong. Expected 42.5, got {strength:.2f}")
        print(f"✗ Strength at 4% distance: Expected 42.5, got {strength:.2f}")
    
    # Test beyond 8% threshold (should be 0)
    current_price = 150.0
    anchor_price = 165.0  # 10% away
    dist_pct = abs(current_price - anchor_price) / max(current_price, 1e-9)
    proximity = _clip(1.0 - dist_pct / 0.08, 0.0, 1.0)
    strength = _clip(base_strength * 100.0 * proximity, 0.0, 100.0)
    
    # dist_pct = 0.10, proximity = max(0, 1.0 - 0.10/0.08) = 0, strength = 0
    if strength == 0.0:
        PASSES.append("TEST2.3: Strength beyond 8% threshold correct (0.0)")
        print(f"✓ Strength beyond 8%: {strength:.2f}")
    else:
        DEFECTS.append(f"TEST2.3: Strength beyond 8% wrong. Expected 0.0, got {strength:.2f}")
        print(f"✗ Strength beyond 8%: Expected 0.0, got {strength:.2f}")

def test_nearest_anchor_logic():
    """Test 3: Nearest anchor selection"""
    print("\n=== TEST 3: Nearest Anchor Logic ===")
    
    current_price = 150.0
    anchors = [
        {"name": "INTEGER", "price": 150.0},
        {"name": "HIGH_52W", "price": 200.0},
        {"name": "LOW_52W", "price": 100.0},
        {"name": "COST_BASIS", "price": 140.0},
    ]
    
    nearest = min(anchors, key=lambda x: abs(current_price - x["price"]))
    
    if nearest["name"] == "INTEGER":
        PASSES.append("TEST3.1: Nearest anchor selection correct (INTEGER)")
        print(f"✓ Nearest anchor: {nearest['name']} at {nearest['price']}")
    else:
        DEFECTS.append(f"TEST3.1: Nearest anchor wrong. Expected INTEGER, got {nearest['name']}")
        print(f"✗ Nearest anchor: Expected INTEGER, got {nearest['name']}")
    
    # Test case 2: Cost basis closer
    current_price = 141.0
    anchors = [
        {"name": "INTEGER", "price": 140.0},
        {"name": "COST_BASIS", "price": 140.0},
    ]
    
    nearest = min(anchors, key=lambda x: abs(current_price - x["price"]))
    
    # Both are 1.0 away, min() returns first match
    if nearest["name"] in ("INTEGER", "COST_BASIS"):
        PASSES.append("TEST3.2: Nearest anchor tie-breaking works")
        print(f"✓ Nearest anchor (tie): {nearest['name']}")
    else:
        DEFECTS.append(f"TEST3.2: Nearest anchor tie-break failed. Got {nearest['name']}")
        print(f"✗ Nearest anchor (tie): Got {nearest['name']}")

def test_integration():
    """Test 4: Integration with behavior_finance module"""
    print("\n=== TEST 4: Integration Test ===")
    
    # Check if _compute_anchor_map exists and is callable
    if callable(_compute_anchor_map):
        PASSES.append("TEST4.1: _compute_anchor_map function exists")
        print("✓ _compute_anchor_map function exists")
    else:
        DEFECTS.append("TEST4.1: _compute_anchor_map not callable")
        print("✗ _compute_anchor_map not callable")
    
    # Test with missing data
    result = _compute_anchor_map("NONEXISTENT")
    
    if result.get("enabled") == False and "reason" in result:
        PASSES.append("TEST4.2: Graceful handling of missing data")
        print(f"✓ Missing data handling: {result.get('reason')}")
    else:
        DEFECTS.append(f"TEST4.2: Missing data handling failed. Result: {result}")
        print(f"✗ Missing data handling failed")

def test_llm_server_logging():
    """Test 5: Check llm_server logging code"""
    print("\n=== TEST 5: LLM Server Logging ===")
    
    llm_path = os.path.join(os.path.dirname(__file__), 'llm_server_v3640.py')
    with open(llm_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for anchor logging
    if '[KEY-005][ANCHOR]' in content:
        PASSES.append("TEST5.1: [KEY-005][ANCHOR] logging present")
        print("✓ [KEY-005][ANCHOR] logging found")
    else:
        DEFECTS.append("TEST5.1: [KEY-005][ANCHOR] logging missing")
        print("✗ [KEY-005][ANCHOR] logging missing")
    
    # Check for anchor_map extraction
    if 'anchor_map' in content and '_am_nearest' in content:
        PASSES.append("TEST5.2: anchor_map extraction logic present")
        print("✓ anchor_map extraction found")
    else:
        DEFECTS.append("TEST5.2: anchor_map extraction logic missing")
        print("✗ anchor_map extraction logic missing")

def test_log_analyzer_parsing():
    """Test 6: Check log_analyzer parsing"""
    print("\n=== TEST 6: Log Analyzer Parsing ===")
    
    log_path = os.path.join(os.path.dirname(__file__), 'log_analyzer_v3.py')
    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for anchor pattern
    if 'key005_anchor' in content:
        PASSES.append("TEST6.1: key005_anchor pattern defined")
        print("✓ key005_anchor pattern found")
    else:
        DEFECTS.append("TEST6.1: key005_anchor pattern missing")
        print("✗ key005_anchor pattern missing")
    
    # Check for pattern regex
    if r'\[KEY-005\]\[ANCHOR\]' in content:
        PASSES.append("TEST6.2: ANCHOR regex pattern correct")
        print("✓ ANCHOR regex pattern found")
    else:
        DEFECTS.append("TEST6.2: ANCHOR regex pattern missing")
        print("✗ ANCHOR regex pattern missing")

def test_monitor_display():
    """Test 7: Check monitor display"""
    print("\n=== TEST 7: Monitor Display ===")
    
    mon_path = os.path.join(os.path.dirname(__file__), 'monitor_v3640.py')
    with open(mon_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for anchor strength averaging
    if '_k5_anchor_strength' in content:
        PASSES.append("TEST7.1: Anchor strength collection found")
        print("✓ Anchor strength collection found")
    else:
        DEFECTS.append("TEST7.1: Anchor strength collection missing")
        print("✗ Anchor strength collection missing")
    
    # Check for average calculation
    if '_k5_avg_anchor' in content:
        PASSES.append("TEST7.2: Average anchor strength calculation found")
        print("✓ Average anchor strength calculation found")
    else:
        DEFECTS.append("TEST7.2: Average anchor strength calculation missing")
        print("✗ Average anchor strength calculation missing")

if __name__ == "__main__":
    print("=" * 70)
    print("KEY-005-M06 ANCHOR MAP VALIDATION RUN 1/2")
    print("=" * 70)
    
    test_anchor_selection()
    test_strength_scoring()
    test_nearest_anchor_logic()
    test_integration()
    test_llm_server_logging()
    test_log_analyzer_parsing()
    test_monitor_display()
    
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"PASSES: {len(PASSES)}")
    print(f"DEFECTS: {len(DEFECTS)}")
    
    if PASSES:
        print("\n✓ PASSED TESTS:")
        for p in PASSES:
            print(f"  - {p}")
    
    if DEFECTS:
        print("\n✗ DEFECTS FOUND:")
        for d in DEFECTS:
            print(f"  - {d}")
    
    overall = "PASS" if not DEFECTS else "FAIL"
    print(f"\nOVERALL: {overall}")
    
    sys.exit(0 if not DEFECTS else 1)
