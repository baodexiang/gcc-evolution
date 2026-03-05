"""
美股仓位热修正工具 v2.1
========================
通过HTTP接口修改仓位，无需停止主程序
配合 v2.840 使用

使用方法：
1. 确保主程序正在运行
2. 在下面的 POSITION_CONFIG 中填入各美股的实际持仓数量
3. 运行: python fix_stock_positions.py
"""

import requests
import json

# ============================================================
# 📝 配置区
# ============================================================

# 主程序地址和端口
SERVER_URL = "http://localhost:6001"

# 美股仓位配置 - 填入实际持仓单位数 (0 = 空仓)
# v2.840: 美股仍为5档，加密货币为5档
POSITION_CONFIG = {
    "TSLA": 2,
    "COIN": 1,
    "RDDT": 1,
    "AMD": 0,
    "NBIS": 0,
    "CRWV": 2,
    "RKLB": 0,
    "HIMS": 2,
    "OPEN": 4,
    "ONDS": 5,
    "PLTR": 1
}

# ============================================================
# 主程序
# ============================================================

def get_current_positions():
    """获取当前仓位"""
    try:
        resp = requests.get(f"{SERVER_URL}/get_positions", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("positions", {})
        else:
            print(f"❌ 获取仓位失败: {resp.text}")
            return {}
    except requests.exceptions.ConnectionError:
        print(f"❌ 无法连接到服务器 {SERVER_URL}")
        print("   请确认主程序正在运行")
        return None
    except Exception as e:
        print(f"❌ 错误: {e}")
        return None

def fix_positions():
    """修正仓位"""
    print("=" * 60)
    print("美股仓位热修正工具 v2.1 (配合v2.840)")
    print("=" * 60)
    print(f"服务器: {SERVER_URL}")
    print()
    
    # 获取当前仓位
    print("📡 获取当前仓位...")
    current = get_current_positions()
    
    if current is None:
        return
    
    # 显示对比
    print("\n" + "-" * 60)
    print(f"{'Symbol':<10} {'当前仓位':<12} {'目标仓位':<12} {'变化':<10}")
    print("-" * 60)
    
    changes = {}
    for symbol, target_units in POSITION_CONFIG.items():
        current_info = current.get(symbol, {})
        current_units = current_info.get("position_units", 0) if current_info else 0
        
        if current_units != target_units:
            change = f"{current_units} → {target_units}"
            changes[symbol] = target_units
        else:
            change = "✓ 一致"
        
        print(f"{symbol:<10} {current_units:<12} {target_units:<12} {change:<10}")
    
    print("-" * 60)
    
    if not changes:
        print("\n✅ 所有仓位已经正确，无需修改")
        return
    
    # 确认修改
    print(f"\n⚠️  将修改以下symbol: {', '.join(changes.keys())}")
    confirm = input("确认修改? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("❌ 已取消")
        return
    
    # 发送修改请求
    print("\n📡 发送修改请求...")
    
    try:
        resp = requests.post(
            f"{SERVER_URL}/fix_position",
            json={"positions": changes},
            timeout=10
        )
        
        if resp.status_code == 200:
            result = resp.json()
            print("\n" + "=" * 60)
            print("✅ 修正完成!")
            print("=" * 60)
            
            for item in result.get("results", []):
                print(f"   {item['symbol']}: {item['old_units']} → {item['new_units']}")
        else:
            print(f"❌ 修改失败: {resp.text}")
    
    except Exception as e:
        print(f"❌ 请求错误: {e}")

def show_positions():
    """仅显示当前仓位"""
    print("=" * 60)
    print("当前仓位状态")
    print("=" * 60)
    
    current = get_current_positions()
    if current is None:
        return
    
    print(f"\n{'Symbol':<10} {'仓位':<8} {'open_buys':<12} {'max_units':<10}")
    print("-" * 45)
    
    for symbol in POSITION_CONFIG.keys():
        info = current.get(symbol, {})
        units = info.get("position_units", 0)
        buys = info.get("open_buys_count", 0)
        max_u = info.get("max_units", 5)
        print(f"{symbol:<10} {units:<8} {buys:<12} {max_u:<10}")

def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        show_positions()
    else:
        fix_positions()

if __name__ == "__main__":
    main()
