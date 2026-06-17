import streamlit as st
import pandas as pd
from datetime import datetime
import json
import os
import urllib.request
import base64

# ==========================================
# 1. 初期設定 & データベース初期化
# ==========================================
st.set_page_config(page_title="AI採用アシスタント MVP", layout="wide")

api_key = os.getenv("GEMINI_API_KEY", "")
db_url = os.getenv("DATABASE_URL", "")

if not api_key:
    st.error("⚠️ GEMINI_API_KEY が設定されていません。StreamlitのSecretsを確認してください。")

try:
    import psycopg2
except ImportError:
    st.error("⚠️ `psycopg2-binary` がインストールされていません。requirements.txtを確認してください。")

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

ANIMAL_LIST = ["未設定", "チータ", "狼", "黒ひょう", "ライオン", "虎", "たぬき", "コアラ", "ゾウ", "ひつじ", "ペガサス", "猿", "こじか"]

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
・苦手な仕事（どう向き合うか）：
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

def get_db_connection():
    if db_url:
        url = db_url.replace("postgresql://", "postgres://") if "postgresql://" in db_url else db_url
        return psycopg2.connect(url)
    else:
        import sqlite3
        return sqlite3.connect("interview_assistant.db")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        university TEXT,
        birth_date TEXT,
        status TEXT,
        interview_date TEXT,
        background_memo TEXT,
        animals_json TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS candidate_notes (
        candidate_id INTEGER PRIMARY KEY,
        raw_interview_memo TEXT,
        ai_report_json TEXT,
        final_judgment_memo TEXT,
        pre_profile_report TEXT
    )
    """)
    conn.commit()
    conn.close()

if db_url:
    init_db()

def calculate_numerology(birth_date_str):
    if not birth_date_str or birth_date_str == "不明":
        return "未設定"
    digits = [int(d) for d in birth_date_str if d.isdigit()]
    total = sum(digits)
    while total > 9 and total not in [11, 22, 33]:
        total = sum(int(d) for d in str(total))
    return f"{total}番"

def ask_gemini(prompt_text, image_bytes=None, mime_type=None):
    if not api_key: return "APIキーが設定されていません。"
    models_to_try = [
        ("v1", "gemini-2.5-flash"), ("v1beta", "gemini-2.5-flash"),
        ("v1", "gemini-1.5-flash"), ("v1beta", "gemini-1.5-flash")
    ]
    
    parts = [{"text": prompt_text}]
    if image_bytes and mime_type:
        parts.insert(0, {
            "inlineData": {
                "mimeType": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8")
            }
        })
        
    data = {"contents": [{"parts": parts}]}
    
    for version, model in models_to_try:
        target_url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={api_key}"
        req = urllib.request.Request(target_url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read().decode("utf-8"))["candidates"][0]["content"]["parts"][0]["text"]
        except: continue
    return "⚠️ Google AIへの接続に失敗しました。"

if "selected_candidate_id" not in st.session_state: st.session_state["selected_candidate_id"] = None

# ==========================================
# 3. Streamlit UI 構築 (綺麗な st.tabs のみに完全修復)
# ==========================================
main_tabs = st.tabs(["📋 候補者一覧・登録", "🔎 面接・評価（詳細画面）"])

# --- タブ1: 候補者一覧・登録 ---
with main_tabs[0]:
    st.header("候補者新規登録")
    with st.expander("➕ 新しい候補者を手動で追加する"):
        with st.form("add_candidate_form"):
            st.subheader("【1】基本情報")
            c_name = st.text_input("候補者氏名（必須）")
            c_univ = st.text_input("大学名・所属")
            is_birth_unknown = st.checkbox("生年月日が不明")
            c_birth = st.date_input("生年月日", value=datetime(2002, 1, 1))
            c_status = st.selectbox("ステータス", ["面接予定", "日程調整待ち", "合否連絡待ち", "長期間放置候補者"])
            c_date = st.text_input("面接予定日時 (例: 2026-06-20 14:00)")
            c_bg = st.text_area("経歴・自己PR・事前情報")
            
            st.divider()
            st.subheader("🔮 【2】5アニマル情報入力")
            st.markdown("🔗 **[5アニマル診断はこちら（外部サイト）](https://www.doubutsu-uranai.com/uranai_chara_5animals.php)**")
            
            st.markdown("📸 **【時短】スマホやPCでキャプチャした診断結果の画像を下に貼り付けると、AIが5キャラを自動で読み取って登録します！**")
            uploaded_file = st.file_uploader("ここにスクショ画像をドラッグ＆ドロップ、またはクリップボードからコピペ(Ctrl+V)", type=["png", "jpg", "jpeg"])
            
            st.write("💡 画像がない場合は、以下の手動セレクトボックスから選んでください。")
            col_a1, col_a2, col_a3, col_a4, col_a5 = st.columns(5)
            with col_a1: honsitsu = st.selectbox("本質キャラ", ANIMAL_LIST, index=4) 
            with col_a2: hyomen = st.selectbox("表面キャラ", ANIMAL_LIST, index=2)   
            with col_a3: kakure = st.selectbox("隠れキャラ", ANIMAL_LIST, index=9)   
            with col_a4: kibo = st.selectbox("希望キャラ", ANIMAL_LIST, index=5)     
            with col_a5: kettei = st.selectbox("意思決定キャラ", ANIMAL_LIST, index=11) 
            
            if st.form_submit_button("候補者を登録"):
                if c_name:
                    birth_str = "不明" if is_birth_unknown else str(c_birth)
                    animals_json = json.dumps({"本質": honsitsu, "表面": hyomen, "隠れ": kakure, "希望": kibo, "意思決定": kettei}, ensure_ascii=False)
                    
                    if uploaded_file is not None:
                        with st.spinner("📷 AIがスクショから5アニマルを自動解読中..."):
                            img_bytes = uploaded_file.read()
                            m_type = uploaded_file.type
                            img_prompt = f"""
                            この画像は「動物占い（5アニマル）」の診断結果画面です。
                            画像の中から「本質」「表面」「隠れ」「希望」「意思決定」の5つのキャラクター名を読み取ってください。
                            
                            必ず以下の有効なキャラクター名リストの中から一致するものを選んでください。
                            有効なキャラリスト: {ANIMAL_LIST}
                            
                            出力は必ず以下の純粋なJSONフォーマットのみにしてください。他の挨拶や説明は一切不要です。
                            {{
                                "本質": "○○",
                                "表面": "○○",
                                "隠れ": "○○",
                                "希望": "○○",
                                "意思決定": "○○"
                            }}
                            """
                            ai_json_str = ask_gemini(img_prompt, img_bytes, m_type)
                            try:
                                clean_json = ai_json_str.replace("```json", "").replace("```", "").strip()
                                animals_dict = json.loads(clean_json)
                                animals_json = json.dumps(animals_dict, ensure_ascii=False)
                            except:
                                pass
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                    INSERT INTO candidates (name, university, birth_date, status, interview_date, background_memo, animals_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (c_name, c_univ, birth_str, c_status, c_date, c_bg, animals_json))
                    conn.commit()
                    conn.close()
                    st.success(f"候補者「{c_name}」を登録しました！")
                    st.rerun()

    st.header("🧐 今日やるべきこと ＆ 候補者一覧")
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT id, name, university, status, interview_date FROM candidates ORDER BY id DESC", conn)
    conn.close()
    
    if not df.empty:
        st.write("### 登録済み候補者一覧")
        for index, row in df.iterrows():
            c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns([1, 2, 2, 2, 1.5])
            with c_col1: st.write(f"ID: {row['id']}")
            with c_col2: st.markdown(f"**{row['name']}**")
            with c_col3: st.write(row['university'])
            with c_col4: st.caption(f"【{row['status']}】 {row['interview_date'] or ''}")
            with c_col5:
                if st.button("詳細・面接へ 🔍", key=f"det_{row['id']}"):
                    st.session_state["selected_candidate_id"] = int(row['id'])
                    st.success(f"🎯 【{row['name']}】さんの選考データをセットしました！上の「🔎 面接・評価（詳細画面）」タブを押してください！")
    else:
        st.info("現在登録されている候補者は居ません。")

# --- タブ2: 面接・評価（詳細画面） ---
with main_tabs[1]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM candidates ORDER BY id DESC")
    candidates_list = cursor.fetchall()
    conn.close()
    
    if not candidates_list:
        st.info("候補者が登録されていません。「📋 候補者一覧・登録」タブで候補者を選んでください。")
    else:
        c_options = {c[1]: c[0] for c in candidates_list}
        default_idx = 0
        if st.session_state["selected_candidate_id"] in c_options.values():
            default_idx = list(c_options.values()).index(st.session_state["selected_candidate_id"])
            
        selected_c_name = st.selectbox("選考・面接を行う候補者を選択してください", list(c_options.keys()), index=default_idx)
        c_id = c_options[selected_c_name]
        st.session_state["selected_candidate_id"] = c_id
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, university, birth_date, status, interview_date, background_memo, animals_json FROM candidates WHERE id=%s", (c_id,))
        c_data = cursor.fetchone()
        
        cursor.execute("SELECT raw_interview_memo, ai_report_json, final_judgment_memo, pre_profile_report FROM candidate_notes WHERE candidate_id=%s", (c_id,))
        notes_data = cursor.fetchone()
        conn.close()
        
        id_val, name, university, birth_date, status, interview_date, background_memo, animals_json = c_data
        
        raw_memo = notes_data[0] if (notes_data and notes_data[0]) else MEMO_TEMPLATE
        ai_report = notes_data[1] if (notes_data and notes_data[1]) else ""
        final_memo = notes_data[2] if (notes_data and notes_data[2]) else ""
        saved_pre_profile = notes_data[3] if (notes_data and notes_data[3]) else ""
        
        c_fortune = json.loads(animals_json) if animals_json else {"本質": "未設定", "表面": "未設定", "隠れ": "未設定", "希望": "未設定", "意思決定": "未設定"}
        c_num = calculate_numerology(birth_date)
        
        sub_tabs = st.tabs(["⏮️ 面接前（準備・占い・相性）", "⏺️ 面接中（リアルタイム）", "⏭️ 面接後（評価レポート）"])
        
        with sub_tabs[0]:
            col_info, col_fortune = st.columns(2)
            with col_info:
                st.markdown(f"**氏名:** {name}  \n**所属:** {university}  \n**ステータス:** {status}  \n**面接日時:** {interview_date}  \n**生年月日:** {birth_date}")
                st.info(f"**事前情報:**\n{background_memo}")
            with col_fortune:
                st.subheader("🔮 登録された占いプロファイル")
                st.success(f"**数秘:** {c_num}")
                for role, animal in c_fortune.items(): st.markdown(f"- **{role}:** {animal}")
                
            st.divider()
            if st.button("AI相性診断＆事前アドバイスを生成（自動保存）", key="pre_ai_btn"):
                with st.spinner("Geminiがビジネス視点での相性を分析中..."):
                    my_fortune_str = ", ".join([f"{k}:{v}" for k, v in MY_PROFILE["five_animals"].items()])
                    c_fortune_str = ", ".join([f"{k}:{v}" for k, v in c_fortune.items()])
                    
                    prompt = f"""
                    あなたはプロの組織開発コンサルタント、および採用面接官です。
                    動物占い（5アニマル）と数秘術を「ビジネスのマネジメントと採用・組織運営」の視点から紐解き、プロファイルを行います。
                    恋愛の要素は一切含めず、完全に【上司と部下】【インターン採用としての適性】の観点のみで出力してください。

                    ■ 面接官「マキコさん」の情報
                    - 数秘: {MY_PROFILE['numerology']}番
                    - 5アニマル: {my_fortune_str}

                    ■ インターン候補生「{name}」の情報
                    - 数秘: {c_num}
                    - 5アニマル: {c_fortune_str}
                    - 事前経歴・自己PR: {background_memo}

                    【超重要ルール】
                    以下の4つのセクション構成で出力してください。
                    各セクションの解説は、面接直前に30秒で読めるよう、必ず「300文字前後」に要約して、簡潔に分かりやすくまとめてください。
                    4の質問候補は、そのままマキコさんがフランクに口頭で読み上げられるセリフにしてください。

                    1. 【候補者の基本特徴・強みの仮説】（ビジネスでの強み）
                    2. 【仕事への姿勢・リモート環境下での人間関係の傾向】
                    3. 【上司マキコからのマネジメント・コミュニケーション攻略法】
                    4. 【本日ぶつけるべき深掘り質問候補3選】（そのまま使えるカンペセリフ）
                    """
                    ai_res = ask_gemini(prompt)
                    saved_pre_profile = ai_res
                    
                    new_memo_content = raw_memo
                    try:
                        strategy_part = ai_res.split("3. 【上司マキコからのマネジメント・コミュニケーション攻略法】")[1].split("4. 【本日ぶつけるべき深掘り質問候補3選】")[0].strip()
                        questions_part = ai_res.split("4. 【本日ぶつけるべき深掘り質問候補3選】")[1].strip()
                        append_text = f"\n\n=========================================\n🚨 AI事前カンペ（自動挿入）\n=========================================\n■ マネジメント・コミュニケーション攻略法:\n{strategy_part}\n\n■ ぶつけるべき質問3選:\n{questions_part}"
                        if "🚨 AI事前カンペ（自動挿入）" not in raw_memo:
                            new_memo_content = raw_memo + append_text
                    except:
                        pass
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                    INSERT INTO candidate_notes (candidate_id, raw_interview_memo, ai_report_json, final_judgment_memo, pre_profile_report)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (candidate_id) DO UPDATE 
                    SET raw_interview_memo=EXCLUDED.raw_interview_memo, pre_profile_report=EXCLUDED.pre_profile_report
                    """, (c_id, new_memo_content, ai_report, final_memo, ai_res))
                    conn.commit()
                    conn.close()
                    st.session_state[f"cached_memo_{c_id}"] = new_memo_content
                    st.rerun()
            
            if saved_pre_profile: st.info(saved_pre_profile)

        with sub_tabs[1]:
            display_memo = st.session_state.get(f"cached_memo_{c_id}", raw_memo)
            updated_memo = st.text_area("面接メモ（スクロールすると一番下に自動カンペがあります！）", value=display_memo, height=500, key=f"memo_{c_id}")
            if st.button("メモを一時保存"):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO candidate_notes (candidate_id, raw_interview_memo, ai_report_json, final_judgment_memo, pre_profile_report)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (candidate_id) DO UPDATE SET raw_interview_memo=EXCLUDED.raw_interview_memo
                """, (c_id, updated_memo, ai_report, final_memo, saved_pre_profile))
                conn.commit()
                conn.close()
                st.session_state[f"cached_memo_{c_id}"] = updated_memo
                st.success("保存しました。")
                
            if st.button("確認漏れ・追加質問をAIに聞く"):
                with st.spinner("分析中..."):
                    prompt = f"以下メモから不足するビジネス適性項目を2つ選び、フランクな質問のセリフと150字の背景を出力して。\n{updated_memo}"
                    st.warning(ask_gemini(prompt))

        with sub_tabs[2]:
            if st.button("AIレポートを生成する"):
                with st.spinner("生成中..."):
                    ai_report = ask_gemini(f"以下メモから8項目についてビジネスでの強みと懸念、活躍可能性をまとめて。\n{updated_memo}")
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE candidate_notes SET ai_report_json=%s WHERE candidate_id=%s", (ai_report, c_id))
                    conn.commit()
                    conn.close()
            if ai_report: st.markdown(ai_report)
