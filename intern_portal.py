import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import json
import os

# ==========================================
# 1. 初期設定 & データベース初期化
# ==========================================
st.set_page_config(page_title="AI採用アシスタント MVP", layout="wide")

# Google Gemini APIの初期化確認
api_key = os.getenv("GEMINI_API_KEY", "")
if not api_key:
    st.error("⚠️ GEMINI_API_KEY が設定されていません。StreamlitのSecretsを確認してください。")

DB_FILE = "interview_assistant.db"

# マキコさんのプロファイル
MY_PROFILE = {
    "name": "マキコ",
    "numerology": 8,
    "five_animals": {
        "本質": "コアラ",
        "表面": "こじか",
        "隠れ": "コアラ",
        "希望": "狼",
        "意思決定": "ペガサス"
    }
}

# 12キャラのリスト
ANIMAL_LIST = ["未設定", "チータ", "狼", "黒ひょう", "ライオン", "虎", "たぬき", "コアラ", "ゾウ", "ひつじ", "ペガサス", "猿", "こじか"]

# 📝 面談メモ用テンプレート
MEMO_TEMPLATE = """=========================================
【1】基本情報・勤務条件
=========================================
・年齢：
・住所：
・家族構成：
・希望シフト（曜日・時間帯）：
・出勤NGな日・時間帯：
・現在の勤務状況（掛け持ちなど）：
・勤務上の配慮事項（体調、家庭事情など）：

=========================================
【2】フルリモート適性・業務スキル
=========================================
■ 出社可能か？：
■ フルリモートの経験・不安はないか？：
■ 電話対応やコールの経験はあるか？：
■ コール拒否や断りが続いた経験はあるか？どう乗り越える？：

=========================================
【3】志望動機・経験・求めるスキル
=========================================
■ 志望動機・応募のきっかけ：
■ 過去の経験（アルバイト・職務経験・期間・内容）：
■ インターンで経験したいこと・得たいスキル：

=========================================
【4】マキコさんが重視する8項目（エピソード深掘り）
=========================================
💡 [主体性・行動力・成長意欲]
・過去に仕事や学校で「自ら動いて頑張った」経験：
・好きな仕事：

💡 [素直さ・継続力・フィードバック耐性]
・苦手な仕事（どう向きアナウンスか）：
・周りからどんな性格と言われるか：

💡 [コミュニケーション能力]
・お客様対応で意識していること：

=========================================
【5】その他・マキコさん用リマインダー
=========================================
・候補者からの質問、確認したいこと：

⚠️ 最後に必ず確認！【最重要チェック項目】
1. 「こちらに聞きたいこと、確認したいこと、知っておいてほしいことは何ですか？」
2. 勤務開始時期の再確認（いつから動けそうか）
3. 判断基準・選考状況の再確認（いつごろまでに決めたいか、何を見て決めるか）"""

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        university TEXT,
        birth_date TEXT,
        status TEXT,
        interview_date TEXT,
        background_memo TEXT,
        animals_json TEXT
    )
    """)
    try: cursor.execute("ALTER TABLE candidates ADD COLUMN animals_json TEXT")
    except sqlite3.OperationalError: pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS candidate_notes (
        candidate_id INTEGER PRIMARY KEY,
        raw_interview_memo TEXT,
        ai_report_json TEXT,
        final_judgment_memo TEXT,
        FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    conn.close()

init_db()

def calculate_numerology(birth_date_str):
    if not birth_date_str or birth_date_str == "不明":
        return "未設定"
    digits = [int(d) for d in birth_date_str if d.isdigit()]
    total = sum(digits)
    while total > 9 and total not in [11, 22, 33]:
        total = sum(int(d) for d in str(total))
    return f"{total}番"

def get_db_connection():
    return sqlite3.connect(DB_FILE)

# 💡 タイムアウトの上限を「60秒」まで大幅に引き延ばしてじっと待つ関数
def ask_gemini(prompt_text):
    my_key = os.getenv("GEMINI_API_KEY", "")
    if not my_key:
        return "APIキーが設定されていません。"
        
    import urllib.request
    
    models_to_try = [
        ("v1", "gemini-2.5-flash"),
        ("v1beta", "gemini-2.5-flash"),
        ("v1", "gemini-1.5-flash"),
        ("v1beta", "gemini-1.5-flash"),
        ("v1", "gemini-1.0-pro"),
        ("v1beta", "gemini-1.0-pro"),
        ("v1beta", "gemini-pro")
    ]
    
    data = {
        "contents": [{
            "parts": [{"text": prompt_text}]
        }]
    }
    
    for version, model in models_to_try:
        target_url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={my_key}"
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(target_url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                response_body = res.read().decode("utf-8")
                res_json = json.loads(response_body)
                return res_json["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            continue
            
    return f"⚠️ 申し訳ありません。Google AIの全モデルへの接続に失敗しました。"

if "selected_candidate_id" not in st.session_state:
    st.session_state["selected_candidate_id"] = None

# ==========================================
# 3. Streamlit UI 構築
# ==========================================
main_tab1, main_tab2 = st.tabs(["📋 候補者一覧・登録", "🔎 面接・評価（詳細画面）"])

# --- タブ1: 候補者一覧・登録 ---
with main_tab1:
    st.header("候補者新規登録")
    with st.expander("➕ 新しい候補者を手動で追加する"):
        with st.form("add_candidate_form"):
            st.subheader("【1】基本情報")
            c_name = st.text_input("候補者氏名（必須）")
            c_univ = st.text_input("大学名・所属")
            
            is_birth_unknown = st.checkbox("生年月日が不明（占いをスキップ）")
            c_birth = st.date_input("生年月日", value=datetime(2002, 1, 1))
            
            c_status = st.selectbox("ステータス", ["面接予定", "日程調整待ち", "合否連絡待ち", "長期間放置候補者"])
            c_date = st.text_input("面接予定日時 (例: 2026-06-20 14:00)")
            c_bg = st.text_area("経歴・自己PR・事前情報")
            
            st.divider()
            st.subheader("🔮 【2】5アニマル情報入力")
            st.markdown("🔗 **[5アニマル診断はこちら（外部サイト）](https://www.doubutsu-uranai.com/uranai_chara_5animals.php)**")
            
            col_a1, col_a2, col_a3, col_a4, col_a5 = st.columns(5)
            with col_a1: honsitsu = st.selectbox("本質キャラ", ANIMAL_LIST, index=0 if is_birth_unknown else 4) 
            with col_a2: hyomen = st.selectbox("表面キャラ", ANIMAL_LIST, index=0 if is_birth_unknown else 2)   
            with col_a3: kakure = st.selectbox("隠れキャラ", ANIMAL_LIST, index=0 if is_birth_unknown else 9)   
            with col_a4: kibo = st.selectbox("希望キャラ", ANIMAL_LIST, index=0 if is_birth_unknown else 5)     
            with col_a5: kettei = st.selectbox("意思決定キャラ", ANIMAL_LIST, index=0 if is_birth_unknown else 11) 
            
            submit = st.form_submit_button("候補者を登録")
            if submit and c_name:
                birth_str = "不明" if is_birth_unknown else str(c_birth)
                animals_dict = {"本質": honsitsu, "表面": hyomen, "隠れ": kakure, "希望": kibo, "意思決定": kettei}
                animals_json = json.dumps(animals_dict, ensure_ascii=False)
                
                conn = get_db_connection()
                conn.execute("""
                INSERT INTO candidates (name, university, birth_date, status, interview_date, background_memo, animals_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (c_name, c_univ, birth_str, c_status, c_date, c_bg, animals_json))
                conn.commit()
                conn.close()
                st.success(f"候補者「{c_name}」を登録しました！")
                st.rerun()

    st.header("🧐 今日やるべきこと ＆ 候補者一覧")
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT id, name, university, status, interview_date FROM candidates", conn)
    conn.close()
    
    if not df.empty:
        todo_interview = df[df['status'] == "面接予定"]
        todo_contact = df[df['status'] == "合否連絡待ち"]
        
        col1, col2 = st.columns(2)
        with col1: st.error(f"📅 **直近の面接予定:** {len(todo_interview)}件")
        with col2: st.warning(f"✉️ **合否連絡待ち:** {len(todo_contact)}件")
            
        st.write("### 登録済み候補者一覧")
        for index, row in df.iterrows():
            c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns([1, 2, 2, 2, 1.5])
            with c_col1: st.write(f"ID: {row['id']}")
            with c_col2: st.markdown(f"**{row['name']}**")
            with c_col3: st.write(row['university'])
            with c_col4: st.caption(f"【{row['status']}】 {row['interview_date'] or ''}")
            with c_col5:
                if st.button("詳細・面接へ 🔍", key=f"det_{row['id']}"):
                    st.session_state["selected_candidate_id"] = row['id']
                    st.rerun()
    else:
        st.info("現在登録されている候補者は居ません。")

# --- タブ2: 面接・評価（詳細画面） ---
with main_tab2:
    conn = get_db_connection()
    candidates_list = conn.execute("SELECT id, name FROM candidates").fetchall()
    conn.close()
    
    if not candidates_list:
        st.info("候補者が登録されていません。「📋 候補者一覧・登録」タブから登録を行ってください。")
    else:
        c_options = {c[1]: c[0] for c in candidates_list}
        default_idx = 0
        if st.session_state["selected_candidate_id"] in c_options.values():
            default_idx = list(c_options.values()).index(st.session_state["selected_candidate_id"])
            
        selected_c_name = st.selectbox("選考・面接を行う候補者を選択してください", list(c_options.keys()), index=default_idx)
        c_id = c_options[selected_c_name]
        st.session_state["selected_candidate_id"] = c_id
        
        conn = get_db_connection()
        c_data = conn.execute("SELECT id, name, university, birth_date, status, interview_date, background_memo FROM candidates WHERE id=?", (c_id,)).fetchone()
        
        try:
            animals_json_row = conn.execute("SELECT animals_json FROM candidates WHERE id=?", (c_id,)).fetchone()
            animals_json = animals_json_row[0] if animals_json_row else None
        except:
            animals_json = None
            
        notes_data = conn.execute("SELECT * FROM candidate_notes WHERE candidate_id=?", (c_id,)).fetchone()
        conn.close()
        
        id_val, name, university, birth_date, status, interview_date, background_memo = c_data
        
        raw_memo = notes_data[1] if (notes_data and notes_data[1]) else MEMO_TEMPLATE
        ai_report = notes_data[2] if notes_data else ""
        final_memo = notes_data[3] if notes_data else ""
        
        if animals_json:
            c_fortune = json.loads(animals_json)
        else:
            c_fortune = {"本質": "未設定", "表面": "未設定", "隠れ": "未設定", "希望": "未設定", "意思決定": "未設定"}
            
        c_num = calculate_numerology(birth_date)
        
        sub_tab1, sub_tab2, sub_tab3 = st.tabs(["⏮️ 面接前（準備・占い・相性）", "⏺️ 面接中（リアルタイム）", "⏭️ 面接後（評価レポート）"])
        
        # --- 子タブ1: 面接前 ---
        with sub_tab1:
            col_info, col_fortune = st.columns(2)
            with col_info:
                st.subheader("基本情報")
                with st.expander("📝 候補者の基本情報・5アニマルを修正・編集する"):
                    with st.form(f"edit_form_{c_id}"):
                        edit_name = st.text_input("氏名", value=name)
                        edit_univ = st.text_input("大学・所属", value=university)
                        
                        edit_birth_unknown = st.checkbox("生年月日が不明（占いをスキップ）", value=(birth_date == "不明"))
                        try: default_b = datetime.strptime(birth_date, "%Y-%m-%d")
                        except: default_b = datetime(2002, 1, 1)
                        edit_birth = st.date_input("生年月日", value=default_b)
                        
                        edit_status = st.selectbox("ステータス", ["面接予定", "日程調整待ち", "合否連絡待ち", "長期間放置候補者"], index=["面接予定", "日程調整待ち", "合否連絡待ち", "長期間放置候補者"].index(status) if status in ["面接予定", "日程調整待ち", "合否連絡待ち", "長期間放置候補者"] else 0)
                        edit_date = st.text_input("面接予定日時", value=interview_date or "")
                        edit_bg = st.text_area("経歴・自己PR・事前情報", value=background_memo or "")
                        
                        st.write("**🔮 5アニマルの修正**")
                        st.markdown("🔗 **[5アニマル診断はこちら（外部サイト）](https://www.doubutsu-uranai.com/uranai_chara_5animals.php)**")
                        
                        e_col1, e_col2, e_col3, e_col4, e_col5 = st.columns(5)
                        with e_col1: e_honsitsu = st.selectbox("本質", ANIMAL_LIST, index=ANIMAL_LIST.index(c_fortune.get("本質", "未設定")))
                        with e_col2: e_hyomen = st.selectbox("表面", ANIMAL_LIST, index=ANIMAL_LIST.index(c_fortune.get("表面", "未設定")))
                        with e_col3: e_kakure = st.selectbox("隠れ", ANIMAL_LIST, index=ANIMAL_LIST.index(c_fortune.get("隠れ", "未設定")))
                        with e_col4: e_kibo = st.selectbox("希望", ANIMAL_LIST, index=ANIMAL_LIST.index(c_fortune.get("希望", "未設定")))
                        with e_col5: e_kettei = st.selectbox("意思決定", ANIMAL_LIST, index=ANIMAL_LIST.index(c_fortune.get("意思決定", "未設定")))
                        
                        if st.form_submit_button("修正内容を保存する"):
                            edit_birth_str = "不明" if edit_birth_unknown else str(edit_birth)
                            new_animals_json = json.dumps({"本質": e_honsitsu, "表面": e_hyomen, "隠れ": e_kakure, "希望": e_kibo, "意思決定": e_kettei}, ensure_ascii=False)
                            conn = get_db_connection()
                            conn.execute("""
                            UPDATE candidates 
                            SET name=?, university=?, birth_date=?, status=?, interview_date=?, background_memo=?, animals_json=?
                            WHERE id=?
                            """, (edit_name, edit_univ, edit_birth_str, edit_status, edit_date, edit_bg, new_animals_json, c_id))
                            conn.commit()
                            conn.close()
                            st.success("情報を修正しました！")
                            st.rerun()
                
                st.markdown(f"**氏名:** {name}  \n**所属:** {university}  \n**ステータス:** {status}  \n**面接日時:** {interview_date}  \n**生年月日:** {birth_date}")
                st.info(f"**経歴・自己PR・事前情報:**\n{background_memo}")
                
            with col_fortune:
                st.subheader("🔮 候補者の5アニマル ＆ 数秘分析")
                st.success(f"**数秘ナンバー:** {c_num}")
                st.markdown("**【5アニマル内訳】**")
                for role, animal in c_fortune.items():
                    st.markdown(f"- **{role}:** {animal}")
                
            st.divider()
            st.subheader("🤖 AI事前プロファイリング")
            
            if st.button("AI相性診断＆事前アドバイスを生成", key="pre_ai_btn"):
                with st.spinner("Googleに存在する全AIモデルへ自動アタック中..."):
                    my_fortune_str = ", ".join([f"{k}:{v}" for k, v in MY_PROFILE["five_animals"].items()])
                    c_fortune_str = ", ".join([f"{k}:{v}" for k, v in c_fortune.items()])
                    fortune_note = "※候補者の占い情報が『未設定』の場合は、経歴や自己PR、求める8項目を中心とした面接対策を重点的に提案してください。"
                    
                    prompt = f"""
                    動物占い（5アニマル）と数秘術のデータに基づき、プロファイルを行います。
                    面接官「マキコさん」と「候補者」の相性を分析してください。
                    {fortune_note}

                    ■ 面接官（あなた）の情報
                    - お名前: {MY_PROFILE['name']}
                    - 数秘: {MY_PROFILE['numerology']}番
                    - 5アニマル: {my_fortune_str}

                    ■ 候補者の情報
                    - お名前: {name}
                    - 数秘: {c_num}
                    - 5アニマル: {c_fortune_str}
                    - 経歴・自己PR・事前情報: {background_memo}

                    以下の構成で、マキコさんが面接前に頭に入れるべきプロファイリング結果を出力してください。
                    1. 【候補者の基本特徴・強みの仮説】
                    2. 【仕事への姿勢・人間関係の傾向】
                    3. 【面接官マキコとのコミュニケーション攻略法】
                    4. 【本日ぶつけるべき深掘り質問候補3選】
                    """
                    st.session_state[f"pre_ai_{c_id}"] = ask_gemini(prompt)
            
            if f"pre_ai_{c_id}" in st.session_state:
                st.info("💡 AIによる事前プロファイリング結果")
                st.markdown(st.session_state[f"pre_ai_{c_id}"])

        # --- 子タブ2: 面接中（リアルタイム） ---
        with sub_tab2:
            st.subheader("面接リアルタイム議事録・メモ")
            col_memo, col_assist = st.columns([2, 1])
            with col_memo:
                updated_memo = st.text_area("面接の様子や発言をテンプレートに沿って入力してください", value=raw_memo, height=600, key=f"memo_{c_id}")
                if st.button("メモを一時保存"):
                    conn = get_db_connection()
                    conn.execute("""
                    INSERT OR REPLACE INTO candidate_notes (candidate_id, raw_interview_memo, ai_report_json, final_judgment_memo)
                    VALUES (?, ?, ?, ?)
                    """, (c_id, updated_memo, ai_report, final_memo))
                    conn.commit()
                    conn.close()
                    st.success("メモを保存しました。")
            with col_assist:
                st.subheader("💡 AIリアルタイム提案")
                if st.button("確認漏れ・追加質問をAIに聞く"):
                    with st.spinner("分析中..."):
                        # 💡 マキコさん専用のカンペ指示プロプロンプトにアップデート
                        prompt = f"""
                        現在のリアルタイムの面接メモを読み取り、マキコさんが重視する8項目（主体性、素直さ、成長意欲、継続力、コミュ力、フルリモート適性、行動力、フィードバック耐性）の中で「まだ情報が足りない・メモが薄い項目」を自動で最大2つ割り出してください。
                        
                        その上で、マキコさんが面接中に1秒で見てそのまま口頭で読み上げられる「質問のセリフ（カンペ）」と、その質問を投げる「150字前後の背景」をセットで出力してください。
                        
                        【厳密な出力フォーマット】
                        > 💡 **AIからの緊急カンペ：残り時間はここをチェック！**

                        #### ❓ 突っ込み質問①（[割り出した項目名]のチェック）
                        **「[そのまま口頭で言えるマキコさんのフランクな口調の質問のセリフ]」**

                        * 💡 **質問の背景（150字前後）**
                          [なぜこの質問をするのか、現在のメモの不足点と候補者の占いや特徴を絡めた150文字前後の解説]

                        （項目が2つある場合は、同様に「#### ❓ 突っ込み質問②」を作成してください）
                        
                        【現在の面接メモ】:
                        {updated_memo}
                        """
                        st.session_state[f"mid_ai_{c_id}"] = ask_gemini(prompt)
                if f"mid_ai_{c_id}" in st.session_state:
                    st.warning(st.session_state[f"mid_ai_{c_id}"])

        # --- 子タブ3: 面接後 ---
        with sub_tab3:
            st.subheader("🤖 AI評価レポート生成")
            if st.button("AIレポートを生成する"):
                with st.spinner("レポート生成中..."):
                    prompt = f"以下の面接メモを元に、主体性・素直さ・成長意欲・継続力・コミュ力・フルリモート適性・行動力・フィードバック耐性の8項目について強みと懸念点を整理し、育成難易度と活躍可能性を言語化してください。合否判断は書かないでください。\n\nメモ:\n{updated_memo}"
                    ai_report = ask_gemini(prompt)
                    conn = get_db_connection()
                    conn.execute("INSERT OR REPLACE INTO candidate_notes VALUES (?, ?, ?, ?)", (c_id, updated_memo, ai_report, final_memo))
                    conn.commit()
                    conn.close()
            if ai_report:
                st.markdown(ai_report)
            
            st.divider()
            st.subheader("🧠 最終人間判断")
            updated_final_memo = st.text_area("マキコさん自身の最終的な評価・所感・採用判断理由を記入してください", value=final_memo)
            new_status = st.selectbox("選考結果（ステータス更新）", ["合否連絡待ち", "採用決定", "不採用", "日程調整待ち"])
            if st.button("最終判断を確定して保存"):
                conn = get_db_connection()
                conn.execute("INSERT OR REPLACE INTO candidate_notes VALUES (?, ?, ?, ?)", (c_id, updated_memo, ai_report, updated_final_memo))
                conn.execute("UPDATE candidates SET status=? WHERE id=?", (new_status, c_id))
                conn.commit()
                conn.close()
                st.success("保存しました！選考プロセスお疲れ様でした、マキコさん。")
