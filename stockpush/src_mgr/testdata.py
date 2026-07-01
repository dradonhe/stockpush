import requests
import akshare as ak
import baostock as bs
import time

# ============ Akshare 测试 ============
# 给 akshare 的 requests 补上请求头，模拟浏览器访问
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
})

# 替换 akshare 内部的 requests 会话
ak.stock_feature.stock_hist_em.requests = session

# ============ Baostock 测试 ============
def test_baostock_login():
    """测试 baostock 登录"""
    lg = bs.login()
    print(f"Baostock login error_code: {lg.error_code}, error_msg: {lg.error_msg}")
    if lg.error_code != '0':
        print("警告: Baostock 登录失败，数据获取可能受影响")
    else:
        bs.logout()
        print("Baostock 登录/登出成功")

# 带重试的下载
def test_akshare():
    print("\n=== Akshare 测试 ===")
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol="601336",
                period="5",
                start_date="20250427",
                end_date="20250430",
                adjust="qfq"
            )
            print(df)
            return True
        except Exception as e:
            print(f"第{attempt+1}次失败: {e}")
            if attempt < 2:
                print("等待3秒后重试...")
                time.sleep(3)
            else:
                print("3次均失败，请检查网络是否能访问 eastmoney.com")
    return False

if __name__ == "__main__":
    # 先测试 baostock
    test_baostock_login()
    # 再测试 akshare
    test_akshare()
