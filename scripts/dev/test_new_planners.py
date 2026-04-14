#!/usr/bin/env python3
"""
Quick test untuk new planners (CC-CBS, PrioritizedCC, WindowedCC).
Run this before full benchmark.
"""

import sys
sys.path.insert(0, 'src')

from cc_mapf.model import GridMap, Instance, AgentSpec, ConnectivitySpec
from cc_mapf.planners import CCCBSPlanner, PrioritizedCCPlanner, WindowedCCPlanner


def create_simple_instance():
    """Create simple 4-agent test instance."""
    grid = GridMap(width=16, height=16, obstacles=set())
    
    agents = [
        AgentSpec(id='a0', start=(2, 2), goal=(12, 12)),
        AgentSpec(id='a1', start=(2, 12), goal=(12, 2)),
        AgentSpec(id='a2', start=(12, 2), goal=(2, 12)),
        AgentSpec(id='a3', start=(12, 12), goal=(2, 2)),
    ]
    
    return Instance(
        name="test_4agents",
        grid=grid,
        agents=agents,
        connectivity=ConnectivitySpec(radius=5)
    )


def test_cc_cbs(instance):
    """Test CC-CBS planner."""
    print(f"\n{'='*50}")
    print(f"Testing: CC-CBS")
    print(f"{'='*50}")
    
    try:
        planner = CCCBSPlanner(
            connectivity_range=5.0
        )
        
        print(f"  Planning...")
        result = planner.solve(instance, time_limit_s=30.0)
        
        if result.status == "success":
            print(f"  ✓ Success!")
            print(f"  Runtime: {result.runtime_s:.3f}s")
            if result.plan:
                makespan = max(len(p) for p in result.plan.values())
                print(f"  Makespan: {makespan}")
            return True
        else:
            print(f"  ✗ Failed: {result.status}")
            return False
        
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_prioritized_cc(instance):
    """Test Prioritized CC planner."""
    print(f"\n{'='*50}")
    print(f"Testing: PrioritizedCC")
    print(f"{'='*50}")
    
    try:
        planner = PrioritizedCCPlanner(
            connectivity_range=5.0
        )
        
        print(f"  Planning...")
        result = planner.solve(instance, time_limit_s=30.0)
        
        if result.status == "success":
            print(f"  ✓ Success!")
            print(f"  Runtime: {result.runtime_s:.3f}s")
            if result.plan:
                makespan = max(len(p) for p in result.plan.values())
                print(f"  Makespan: {makespan}")
            return True
        else:
            print(f"  ✗ Failed: {result.status}")
            return False
        
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_windowed_cc(instance):
    """Test Windowed CC planner."""
    print(f"\n{'='*50}")
    print(f"Testing: WindowedCC")
    print(f"{'='*50}")
    
    try:
        planner = WindowedCCPlanner(
            window_size=10,
            connectivity_range=5.0
        )
        
        print(f"  Planning...")
        result = planner.solve(instance, time_limit_s=30.0)
        
        if result.status == "success":
            print(f"  ✓ Success!")
            print(f"  Runtime: {result.runtime_s:.3f}s")
            if result.plan:
                makespan = max(len(p) for p in result.plan.values())
                print(f"  Makespan: {makespan}")
            return True
        else:
            print(f"  ✗ Failed: {result.status}")
            return False
        
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("="*60)
    print("CC-MAPF New Planners Test")
    print("="*60)
    
    instance = create_simple_instance()
    print(f"\nTest instance: 4 agents, 16x16 grid")
    
    results = {}
    
    # Test CC-CBS
    results['CC-CBS'] = test_cc_cbs(instance)
    
    # Test PrioritizedCC
    results['PrioritizedCC'] = test_prioritized_cc(instance)
    
    # Test WindowedCC
    results['WindowedCC'] = test_windowed_cc(instance)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {name}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✓ All tests passed! Ready for full benchmark.")
        return 0
    else:
        print("\n✗ Some tests failed. Please fix before running benchmark.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
