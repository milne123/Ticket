import sqlite3
import pandas as pd
import streamlit as st

# 1. 網頁頁面基本設定
st.set_page_config(
    page_title="演唱會自動換票平台", page_icon="🎫", layout="centered"
)

DB_PATH = "tickets.db"


def get_db():
    """開啟資料庫，並啟動 WAL 併發模式"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    """初始化資料庫表單與索引"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id TEXT NOT NULL,
                have_ticket TEXT NOT NULL,
                want_ticket TEXT NOT NULL,
                status TEXT DEFAULT 'WAITING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_status_have ON requests"
            " (status, have_ticket)"
        )
        conn.commit()


init_db()


def find_exchange_cycle(contact_id, have_ticket, want_ticket, max_depth=3):
    """最多 3 人 (兩兩對換與三角互換) 的 DFS 演算法"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, contact_id, have_ticket, want_ticket FROM requests"
            " WHERE status='WAITING'"
        )
        waiting_list = [dict(row) for row in c.fetchall()]

    graph = {}
    for req in waiting_list:
        have = req["have_ticket"]
        graph.setdefault(have, []).append(req)

    def dfs(current_ticket, target_ticket, path, visited_users):
        if len(path) >= max_depth:
            return None
        if current_ticket not in graph:
            return None

        for req in graph[current_ticket]:
            if req["contact_id"] in visited_users:
                continue

            # 成功接回目標票券
            if req["want_ticket"] == target_ticket:
                return path + [req]

            if len(path) + 1 < max_depth - 1:
                visited_users.add(req["contact_id"])
                res = dfs(
                    req["want_ticket"], target_ticket, path + [req], visited_users
                )
                if res:
                    return res
                visited_users.remove(req["contact_id"])
        return None

    return dfs(want_ticket, have_ticket, [], {contact_id})


# ================= 網頁前端介面 =================

st.title("🎫 演唱會換票 / 求票自動媒合系統")
st.caption("透過系統自動對接，避免社群洗版與漏單。提交後系統將立即進行比對！")

# 分頁標籤
tab1, tab2, tab3 = st.tabs(
    ["📝 登記換票/求票", "🔍 目前待媒合看板", "❌ 取消我的登記"]
)

# ----------------- Tab 1: 登記表單 -----------------
with tab1:
    st.subheader("請選擇您的換票條件")

    with st.form("ticket_form", clear_on_submit=True):
        contact_id = st.text_input(
            "LINE ID（必填，僅用於媒合成功時聯繫）",
            placeholder="請務必確認已開啟「允許搜尋ID」",
        )

        col1, col2 = st.columns(2)
        with col1:
            have_date = st.selectbox(
                "【持有】場次日期",
                ["10/20 (六)", "10/21 (日)", "10/22 (一)"],
            )
            have_area = st.selectbox(
                "【持有】票券區域/票價",
                ["VIP區 5800", "A區 4800", "B區 3800", "C區 2800"],
            )

        with col2:
            want_date = st.selectbox(
                "【欲換】場次日期",
                ["10/21 (日)", "10/20 (六)", "10/22 (一)"],
            )
            want_area = st.selectbox(
                "【欲換】票券區域/票價",
                ["B區 3800", "VIP區 5800", "A區 4800", "C區 2800"],
            )

        submitted = st.form_submit_button("🚀 提交並開始自動比對")

    if submitted:
        if not contact_id.strip():
            st.error("⚠️ 請務必填寫您的 LINE ID！")
        else:
            have_ticket = f"{have_date} {have_area}"
            want_ticket = f"{want_date} {want_area}"

            if have_ticket == want_ticket:
                st.warning("⚠️ 持有與欲換的場次區域相同，無需換票！")
            else:
                # 執行搜尋
                chain = find_exchange_cycle(
                    contact_id.strip(), have_ticket, want_ticket, max_depth=3
                )

                if chain:
                    # 組合鏈路
                    all_participants = [
                        {
                            "contact": contact_id.strip(),
                            "have": have_ticket,
                            "want": want_ticket,
                        }
                    ]
                    for item in chain:
                        all_participants.append(
                            {
                                "contact": item["contact_id"],
                                "have": item["have_ticket"],
                                "want": item["want_ticket"],
                            }
                        )

                    # 更新資料庫為已配對
                    with get_db() as conn:
                        c = conn.cursor()
                        for item in chain:
                            c.execute(
                                "UPDATE requests SET status='MATCHED' WHERE"
                                " id=?",
                                (item["id"],),
                            )
                        conn.commit()

                    st.balloons()
                    st.success(
                        f"🎉 恭喜！當場成功完成【{len(all_participants)} 方連環換票】！"
                    )

                    st.markdown("### 🔄 換票對接名單與加好友連結：")
                    for idx, p in enumerate(all_participants, 1):
                        line_link = (
                            f"https://line.me/R/ti/p/~{p['contact'].strip()}"
                        )
                        st.markdown(
                            f"**{idx}. LINE ID:** `{p['contact']}` （持"
                            f" {p['have']} 換 {p['want']}）  \n👉 [點此直接加"
                            f" LINE 好友]({line_link})"
                        )
                    st.info("💡 請主動點擊上方連結聯繫對應成員洽談換票事宜！")

                else:
                    # 無相符對象，寫入資料庫
                    with get_db() as conn:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO requests (contact_id, have_ticket,"
                            " want_ticket, status) VALUES (?, ?, ?, 'WAITING')",
                            (contact_id.strip(), have_ticket, want_ticket),
                        )
                        conn.commit()

                    st.info(
                        "✅ 已為您登記至看板！目前暫無完全吻合的需求，當後續有人提交符合條件的單子時，請關注『目前待媒合看板』。"
                    )

# ----------------- Tab 2: 看板 -----------------
with tab2:
    st.subheader("📋 當前等待中的需求")
    with get_db() as conn:
        df = pd.read_sql_query(
            "SELECT contact_id AS 'LINE ID', have_ticket AS '持有票券',"
            " want_ticket AS '欲換票券', created_at AS '登記時間' FROM requests"
            " WHERE status='WAITING' ORDER BY id DESC",
            conn,
        )

    if not df.empty:
        # 部分遮蔽 LINE ID 護隱私 (也可改為不遮蔽)
        df["LINE ID"] = df["LINE ID"].apply(
            lambda x: x[:2] + "****" + x[-1:] if len(x) > 3 else x
        )
        st.dataframe(df, use_container_width=True)
    else:
        st.write("🎉 目前沒有等待中的換票需求，或全部已媒合成功！")

# ----------------- Tab 3: 取消登記 -----------------
with tab3:
    st.subheader("🗑️ 取消 / 下架我的登記")
    cancel_id = st.text_input("請輸入您當初登記的 LINE ID：")
    if st.button("確認取消登記"):
        if cancel_id.strip():
            with get_db() as conn:
                c = conn.cursor()
                c.execute(
                    "UPDATE requests SET status='CANCELLED' WHERE"
                    " contact_id=? AND status='WAITING'",
                    (cancel_id.strip(),),
                )
                conn.commit()
                affected = c.rowcount

            if affected > 0:
                st.success(
                    f"✅ 已成功下架 {affected} 筆等待中的需求！"
                )
            else:
                st.warning("ℹ️ 未查到該 LINE ID 有等待中的需求。")

