import sqlite3
import pandas as pd
import streamlit as st

# 1. 網頁頁面基本設定
st.set_page_config(
    page_title="演唱會換票 / 讓票 / 求票自動媒合平台",
    page_icon="🎫",
    layout="centered",
)

DB_PATH = "tickets.db"


def get_db():
  """開啟資料庫連線，啟動 WAL 併發模式與超時機制"""
  conn = sqlite3.connect(DB_PATH, timeout=10.0)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA journal_mode=WAL;")
  return conn


def init_db():
  """初始化資料庫表單、索引與欄位自動升級"""
  with get_db() as conn:
    c = conn.cursor()
    c.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id TEXT NOT NULL,
                req_type TEXT DEFAULT 'SWAP',
                have_ticket TEXT,
                want_ticket TEXT,
                qty INTEGER DEFAULT 1,
                status TEXT DEFAULT 'WAITING',
                matched_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # 自動補充舊版本欄位
    for col, col_type in [
        ("qty", "INTEGER DEFAULT 1"),
        ("matched_info", "TEXT"),
        ("req_type", "TEXT DEFAULT 'SWAP'"),
    ]:
      try:
        c.execute(f"ALTER TABLE requests ADD COLUMN {col} {col_type};")
      except sqlite3.OperationalError:
        pass

    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_status_type ON requests (status,"
        " req_type)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_contact_status ON requests"
        " (contact_id, status)"
    )
    conn.commit()


init_db()


def find_exchange_cycle(contact_id, have_ticket, want_ticket, qty, max_depth=3):
  """【換票演算法】最多 3 人 (兩兩對換與三角互換) 的 DFS 搜尋"""
  with get_db() as conn:
    c = conn.cursor()
    c.execute(
        "SELECT id, contact_id, have_ticket, want_ticket, qty FROM requests"
        " WHERE status='WAITING' AND req_type='SWAP' AND qty=?",
        (qty,),
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


def find_transfer_seek_match(req_type, ticket, qty):
  """【讓票/求票演算法】一對一單向精準對接"""
  target_type = "SEEK" if req_type == "TRANSFER" else "TRANSFER"
  target_col = "want_ticket" if req_type == "TRANSFER" else "have_ticket"

  with get_db() as conn:
    c = conn.cursor()
    c.execute(
        f"""
            SELECT id, contact_id, have_ticket, want_ticket, qty 
            FROM requests 
            WHERE status='WAITING' AND req_type=? AND {target_col}=? AND qty=?
            ORDER BY id ASC LIMIT 1
        """,
        (target_type, ticket, qty),
    )
    row = c.fetchone()
    return dict(row) if row else None


# ================= 網頁前端介面 =================

st.title("🎫 演唱會換票 / 讓票 / 求票自動媒合系統")
st.caption("自動進行多方換票與讓求票對接，避免社群洗版與漏單！")

DATE_OPTIONS = ["1/9", "1/10"]
AREA_OPTIONS = [
    "6980區",
    "5980區",
    "4980區",
    "3980區",
    "2980區",
]
QTY_OPTIONS = [1, 2, 3, 4]

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔄 登記換票",
    "🎟️ 讓票 / 求票",
    "📋 待媒合看板",
    "❌ 取消登記",
    "🔎 查詢配對結果",
])

# ----------------- Tab 1: 登記換票 -----------------
with tab1:
  st.subheader("🔄 換票需求登記（以票換票）")

  with st.form("swap_form", clear_on_submit=True):
    contact_id = st.text_input(
        "LINE ID（必填）", placeholder="請確認已開啟「允許搜尋ID」"
    )

    col1, col2 = st.columns(2)
    with col1:
      have_date = st.selectbox("【持有】場次日期", DATE_OPTIONS, key="s_hd")
      have_area = st.selectbox("【持有】區域票價", AREA_OPTIONS, key="s_ha")

    with col2:
      want_date = st.selectbox("【欲換】場次日期", DATE_OPTIONS, key="s_wd")
      want_area = st.selectbox("【欲換】區域票價", AREA_OPTIONS, key="s_wa")

    qty = st.selectbox("換票張數", QTY_OPTIONS, index=0, key="s_qty")
    submitted = st.form_submit_button("🚀 提交換票並自動比對")

  if submitted:
    if not contact_id.strip():
      st.error("⚠️ 請務必填寫您的 LINE ID！")
    else:
      have_ticket = f"{have_date} {have_area}"
      want_ticket = f"{want_date} {want_area}"

      if have_ticket == want_ticket:
        st.warning("⚠️ 持有與欲換場次區域相同，無需換票！")
      else:
        chain = find_exchange_cycle(
            contact_id.strip(), have_ticket, want_ticket, qty, max_depth=3
        )

        if chain:
          all_participants = [{
              "contact": contact_id.strip(),
              "have": have_ticket,
              "want": want_ticket,
              "qty": qty,
          }]
          for item in chain:
            all_participants.append({
                "contact": item["contact_id"],
                "have": item["have_ticket"],
                "want": item["want_ticket"],
                "qty": item["qty"],
            })

          info_lines = [
              f"{idx}. LINE ID: {p['contact']}（持 {p['have']} 換"
              f" {p['want']}｜{p['qty']}張）"
              for idx, p in enumerate(all_participants, 1)
          ]
          info_text = "\n".join(info_lines)

          with get_db() as conn:
            c = conn.cursor()
            for item in chain:
              c.execute(
                  "UPDATE requests SET status='MATCHED', matched_info=? WHERE"
                  " id=?",
                  (info_text, item["id"]),
              )
            c.execute(
                "INSERT INTO requests (contact_id, req_type, have_ticket,"
                " want_ticket, qty, status, matched_info) VALUES (?, 'SWAP', ?,"
                " ?, ?, 'MATCHED', ?)",
                (
                    contact_id.strip(),
                    have_ticket,
                    want_ticket,
                    qty,
                    info_text,
                ),
            )
            conn.commit()

          st.balloons()
          st.success(f"🎉 成功完成【{len(all_participants)} 方換票】！")
          for idx, p in enumerate(all_participants, 1):
            line_link = f"https://line.me/R/ti/p/~{p['contact'].strip()}"
            st.markdown(
                f"**{idx}. LINE ID:** `{p['contact']}` （持 {p['have']} 換"
                f" {p['want']}｜{p['qty']}張）  \n👉 [點此加 LINE"
                f" 好友]({line_link})"
            )
        else:
          with get_db() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO requests (contact_id, req_type, have_ticket,"
                " want_ticket, qty, status) VALUES (?, 'SWAP', ?, ?, ?,"
                " 'WAITING')",
                (contact_id.strip(), have_ticket, want_ticket, qty),
            )
            conn.commit()

          st.info(
              f"✅ 已登記換票（{qty}張）至看板！目前暫無吻合需求，可至『🔎"
              " 查詢配對結果』頁面追蹤進度。"
          )

# ----------------- Tab 2: 讓票 / 求票 -----------------
with tab2:
  st.subheader("🎟️ 讓票 / 求票專區")
  st.caption("適合多出票券欲原價轉讓，或是沒買到票求轉讓的成員。")

  action_type = st.radio(
      "請選擇登記類型：",
      ["我想【讓票】（有多票要讓給別人）", "我想【求票】（沒票想求別人轉讓）"],
      horizontal=True,
  )

  is_transfer = "讓票" in action_type
  req_code = "TRANSFER" if is_transfer else "SEEK"

  with st.form("transfer_seek_form", clear_on_submit=True):
    ts_contact_id = st.text_input(
        "LINE ID（必填）",
        placeholder="請確認已開啟「允許搜尋ID」",
        key="ts_id",
    )

    col1, col2 = st.columns(2)
    with col1:
      ts_date = st.selectbox(
          "【讓出】場次日期" if is_transfer else "【欲求】場次日期",
          DATE_OPTIONS,
          key="ts_d",
      )
    with col2:
      ts_area = st.selectbox(
          "【讓出】區域票價" if is_transfer else "【欲求】區域票價",
          AREA_OPTIONS,
          key="ts_a",
      )

    ts_qty = st.selectbox("張數", QTY_OPTIONS, index=0, key="ts_qty")
    ts_submitted = st.form_submit_button(
        "🚀 提交讓票登記" if is_transfer else "🚀 提交求票登記"
    )

  if ts_submitted:
    if not ts_contact_id.strip():
      st.error("⚠️ 請務必填寫您的 LINE ID！")
    else:
      ticket_str = f"{ts_date} {ts_area}"
      have_val = ticket_str if is_transfer else "無"
      want_val = "無" if is_transfer else ticket_str

      # 執行一對一精準對接
      match = find_transfer_seek_match(req_code, ticket_str, ts_qty)

      if match:
        other_contact = match["contact_id"]
        seller_id = ts_contact_id.strip() if is_transfer else other_contact
        buyer_id = other_contact if is_transfer else ts_contact_id.strip()

        info_text = (
            f"🎉 【讓票/求票 媒合成功】\n"
            f"• 讓票方 LINE ID: {seller_id} (提供 {ticket_str} {ts_qty}張)\n"
            f"• 求票方 LINE ID: {buyer_id} (需求 {ticket_str} {ts_qty}張)"
        )

        with get_db() as conn:
          c = conn.cursor()
          # 更新原等待者
          c.execute(
              "UPDATE requests SET status='MATCHED', matched_info=? WHERE"
              " id=?",
              (info_text, match["id"]),
          )
          # 新增本次登記紀錄
          c.execute(
              "INSERT INTO requests (contact_id, req_type, have_ticket,"
              " want_ticket, qty, status, matched_info) VALUES (?, ?, ?, ?,"
              " ?, 'MATCHED', ?)",
              (
                  ts_contact_id.strip(),
                  req_code,
                  have_val,
                  want_val,
                  ts_qty,
                  info_text,
              ),
          )
          conn.commit()

        st.balloons()
        st.success("🎉 當場成功媒合到讓求票對象！")
        line_link = f"https://line.me/R/ti/p/~{other_contact.strip()}"
        role_label = "求票對象" if is_transfer else "讓票對象"
        st.markdown(
            f"**對方（{role_label}）LINE ID:** `{other_contact}`  \n👉"
            f" [點此直接加對方 LINE 好友]({line_link})"
        )
      else:
        with get_db() as conn:
          c = conn.cursor()
          c.execute(
              "INSERT INTO requests (contact_id, req_type, have_ticket,"
              " want_ticket, qty, status) VALUES (?, ?, ?, ?, ?, 'WAITING')",
              (ts_contact_id.strip(), req_code, have_val, want_val, ts_qty),
          )
          conn.commit()

        action_label = "讓票" if is_transfer else "求票"
        st.info(
            f"✅ 已為您登記【{action_label}】（{ticket_str}｜{ts_qty}張）至看板！當後續有人登記對應需求時，可隨時在『🔎"
            " 查詢配對結果』查看結果。"
        )

# ----------------- Tab 3: 看板 -----------------
with tab3:
  st.subheader("📋 當前等待中的需求看板")

  sub_tab1, sub_tab2 = st.tabs(["🔄 換票看板", "🎟️ 讓票 / 求票看板"])

  with sub_tab1:
    with get_db() as conn:
      df_swap = pd.read_sql_query(
          "SELECT contact_id AS 'LINE ID', have_ticket AS '持有票券',"
          " want_ticket AS '欲換票券', qty AS '張數', created_at AS '登記時間'"
          " FROM requests WHERE status='WAITING' AND req_type='SWAP' ORDER BY"
          " id DESC",
          conn,
      )
    if not df_swap.empty:
      df_swap["LINE ID"] = df_swap["LINE ID"].apply(
          lambda x: x[:2] + "****" + x[-1:] if len(x) > 3 else x
      )
      st.dataframe(df_swap, use_container_width=True)
    else:
      st.write("🎉 目前沒有等待中的換票需求！")

  with sub_tab2:
    with get_db() as conn:
      df_ts = pd.read_sql_query(
          "SELECT CASE WHEN req_type='TRANSFER' THEN '讓票' ELSE '求票' END AS"
          " '類型', contact_id AS 'LINE ID', CASE WHEN req_type='TRANSFER' THEN"
          " have_ticket ELSE want_ticket END AS '票券資訊', qty AS '張數',"
          " created_at AS '登記時間' FROM requests WHERE status='WAITING' AND"
          " req_type IN ('TRANSFER', 'SEEK') ORDER BY id DESC",
          conn,
      )
    if not df_ts.empty:
      df_ts["LINE ID"] = df_ts["LINE ID"].apply(
          lambda x: x[:2] + "****" + x[-1:] if len(x) > 3 else x
      )
      st.dataframe(df_ts, use_container_width=True)
    else:
      st.write("🎉 目前沒有等待中的讓票或求票需求！")

# ----------------- Tab 4: 取消登記 -----------------
with tab4:
  st.subheader("🗑️ 取消 / 下架我的登記")
  cancel_id = st.text_input("請輸入您當初登記的 LINE ID：", key="cancel_id_input")
  if st.button("確認取消登記"):
    if cancel_id.strip():
      with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE requests SET status='CANCELLED' WHERE contact_id=? AND"
            " status='WAITING'",
            (cancel_id.strip(),),
        )
        conn.commit()
        affected = c.rowcount

      if affected > 0:
        st.success(f"✅ 已成功下架 {affected} 筆等待中的需求！")
      else:
        st.warning("ℹ️ 未查到該 LINE ID 有等待中的需求。")

# ----------------- Tab 5: 查詢配對結果 -----------------
with tab5:
  st.subheader("🔎 查詢個人配對進度")
  search_id = st.text_input(
      "輸入您登記的 LINE ID：", key="search_status_id"
  )

  if st.button("查詢進度"):
    if search_id.strip():
      with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT req_type, status, matched_info, have_ticket, want_ticket,"
            " qty, created_at FROM requests WHERE contact_id=? ORDER BY id"
            " DESC LIMIT 1",
            (search_id.strip(),),
        )
        row = c.fetchone()

      if row:
        rtype = row["req_type"]
        status = row["status"]
        info = row["matched_info"]
        have = row["have_ticket"]
        want = row["want_ticket"]
        q = row["qty"]

        type_map = {"SWAP": "換票", "TRANSFER": "讓票", "SEEK": "求票"}
        st.write(
            f"📌 **您的最新登記 [{type_map.get(rtype, '換票')}]：** 持有 `{have}`"
            f" ➔ 需求 `{want}` （{q}張）"
        )

        if status == "MATCHED":
          st.balloons()
          st.success("🎉 恭喜！您的需求已成功配對！")
          st.markdown("### 🔄 您的對接名單：")
          st.text(info)
          st.info("💡 請直接複製或搜尋名單中的 LINE ID 加好友進行聯繫。")
        elif status == "WAITING":
          st.info("⏳ 目前仍在等待合適的對象，配對成功後在此即可直接查到結果！")
        elif status == "CANCELLED":
          st.warning("⚠️ 此筆需求已被取消。")
      else:
        st.error("❌ 查無此 LINE ID 的登記紀錄。")
