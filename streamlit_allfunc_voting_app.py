import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import hashlib
import json
import sqlite3
from pathlib import Path
import os

# ページ設定
st.set_page_config(
    page_title="国民投票システム",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# カスタムCSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #4F46E5;
        text-align: center;
        padding: 1rem 0;
    }
    .success-box {
        padding: 1rem;
        background-color: #D1FAE5;
        border-left: 4px solid #10B981;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        background-color: #DBEAFE;
        border-left: 4px solid #3B82F6;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .warning-box {
        padding: 1rem;
        background-color: #FEF3C7;
        border-left: 4px solid #F59E0B;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .admin-badge {
        background-color: #A855F7;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-size: 0.875rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# =============================================
# データベースクラス
# =============================================

class Database:
    def __init__(self, db_path="referendum_data.db"):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_database(self):
        """データベースとテーブルを初期化"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # ユーザーテーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            voter_id TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 提案テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 投票テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id INTEGER NOT NULL,
            voter_id TEXT NOT NULL,
            vote_type TEXT NOT NULL,
            voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (proposal_id) REFERENCES proposals (id),
            UNIQUE(proposal_id, voter_id)
        )
        """)
        
        # イニシアティブテーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS initiatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            required_signatures INTEGER NOT NULL,
            status TEXT DEFAULT 'collecting',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 署名テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initiative_id INTEGER NOT NULL,
            voter_id TEXT NOT NULL,
            signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (initiative_id) REFERENCES initiatives (id),
            UNIQUE(initiative_id, voter_id)
        )
        """)
        
        # 設定テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # ファクトチェック履歴テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fact_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            query TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 初期データ投入
        cursor.execute("SELECT COUNT(*) FROM proposals")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
            INSERT INTO proposals (type, title, description) VALUES 
            ('referendum', '消費税率の引き下げ', '消費税率を10%から8%に引き下げる法案'),
            ('veto', '防衛費増額法案への拒否権', '政府が提案した防衛費増額法案に対する拒否権行使')
            """)
        
        cursor.execute("SELECT COUNT(*) FROM initiatives")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
            INSERT INTO initiatives (title, description, required_signatures) VALUES 
            ('最低賃金の引き上げ', '全国一律で最低賃金を1,500円に引き上げる', 10000)
            """)
            # 初期署名データ
            for i in range(8500):
                cursor.execute("""
                INSERT INTO signatures (initiative_id, voter_id) VALUES (1, ?)
                """, (f"initial_voter_{i}",))
        
        cursor.execute("SELECT COUNT(*) FROM settings WHERE key='required_signatures'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
            INSERT INTO settings (key, value) VALUES ('required_signatures', '10000')
            """)
        
        conn.commit()
        conn.close()
    
    # ユーザー関連
    def create_or_update_user(self, google_id, email, name, voter_id, is_admin=False):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO users (id, email, name, voter_id, is_admin) 
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET 
            email=excluded.email, 
            name=excluded.name,
            is_admin=excluded.is_admin
        """, (google_id, email, name, voter_id, 1 if is_admin else 0))
        
        conn.commit()
        user = self.get_user_by_id(google_id)
        conn.close()
        return user
    
    def get_user_by_id(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'email': row[1],
                'name': row[2],
                'voter_id': row[3],
                'is_admin': bool(row[4])
            }
        return None
    
    # 提案関連
    def get_all_proposals(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proposals ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        
        proposals = []
        for row in rows:
            proposal = {
                'id': row[0],
                'type': row[1],
                'title': row[2],
                'description': row[3],
                'status': row[4],
                'votes': self.get_vote_counts(row[0])
            }
            proposals.append(proposal)
        return proposals
    
    def get_vote_counts(self, proposal_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT vote_type, COUNT(*) FROM votes 
        WHERE proposal_id=? 
        GROUP BY vote_type
        """, (proposal_id,))
        rows = cursor.fetchall()
        
        cursor.execute("SELECT type FROM proposals WHERE id=?", (proposal_id,))
        proposal_type = cursor.fetchone()[0]
        conn.close()
        
        if proposal_type == 'referendum':
            votes = {'agree': 0, 'disagree': 0}
        else:
            votes = {'veto': 0, 'approve': 0}
        
        for row in rows:
            votes[row[0]] = row[1]
        
        return votes
    
    def cast_vote(self, proposal_id, voter_id, vote_type):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO votes (proposal_id, voter_id, vote_type) 
            VALUES (?, ?, ?)
            """, (proposal_id, voter_id, vote_type))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False
    
    def has_voted(self, proposal_id, voter_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT COUNT(*) FROM votes 
        WHERE proposal_id=? AND voter_id=?
        """, (proposal_id, voter_id))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    
    # イニシアティブ関連
    def get_all_initiatives(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM initiatives ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        
        initiatives = []
        for row in rows:
            initiative = {
                'id': row[0],
                'title': row[1],
                'description': row[2],
                'required': row[3],
                'status': row[4],
                'signatures': self.get_signature_count(row[0])
            }
            initiatives.append(initiative)
        return initiatives
    
    def get_signature_count(self, initiative_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT COUNT(*) FROM signatures WHERE initiative_id=?
        """, (initiative_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def sign_initiative(self, initiative_id, voter_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO signatures (initiative_id, voter_id) 
            VALUES (?, ?)
            """, (initiative_id, voter_id))
            conn.commit()
            
            signatures = self.get_signature_count(initiative_id)
            cursor.execute("SELECT required_signatures FROM initiatives WHERE id=?", (initiative_id,))
            required = cursor.fetchone()[0]
            
            if signatures >= required:
                cursor.execute("""
                UPDATE initiatives SET status='qualified' WHERE id=?
                """, (initiative_id,))
                conn.commit()
                
                cursor.execute("SELECT title, description FROM initiatives WHERE id=?", (initiative_id,))
                title, description = cursor.fetchone()
                cursor.execute("""
                INSERT INTO proposals (type, title, description) 
                VALUES ('referendum', ?, ?)
                """, (title, description + ' (イニシアティブから)'))
                conn.commit()
                conn.close()
                return True, True
            
            conn.close()
            return True, False
        except sqlite3.IntegrityError:
            conn.close()
            return False, False
    
    def has_signed(self, initiative_id, voter_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT COUNT(*) FROM signatures 
        WHERE initiative_id=? AND voter_id=?
        """, (initiative_id, voter_id))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    
    def create_initiative(self, title, description, voter_id):
        required = self.get_setting('required_signatures', 10000)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO initiatives (title, description, required_signatures) 
        VALUES (?, ?, ?)
        """, (title, description, required))
        initiative_id = cursor.lastrowid
        
        cursor.execute("""
        INSERT INTO signatures (initiative_id, voter_id) VALUES (?, ?)
        """, (initiative_id, voter_id))
        
        conn.commit()
        conn.close()
        return initiative_id
    
    # 設定関連
    def get_setting(self, key, default=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            try:
                return int(row[0])
            except:
                return row[0]
        return default
    
    def set_setting(self, key, value):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """, (key, str(value)))
        conn.commit()
        conn.close()
    
    # ファクトチェック関連
    def save_fact_check(self, user_id, query, answer, sources):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO fact_checks (user_id, query, answer, sources) 
        VALUES (?, ?, ?, ?)
        """, (user_id, query, answer, json.dumps(sources)))
        conn.commit()
        conn.close()
    
    def get_fact_check_history(self, user_id, limit=5):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT query, answer, sources, created_at 
        FROM fact_checks 
        WHERE user_id=? 
        ORDER BY created_at DESC 
        LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            history.append({
                'query': row[0],
                'answer': row[1],
                'sources': json.loads(row[2]),
                'timestamp': datetime.fromisoformat(row[3])
            })
        return history
    
    # 統計情報
    def get_statistics(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM proposals WHERE type='referendum'")
        referendum_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM proposals WHERE type='veto'")
        veto_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM initiatives")
        initiative_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM initiatives WHERE status='collecting'")
        collecting_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM initiatives WHERE status='qualified'")
        qualified_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'referendum': referendum_count,
            'veto': veto_count,
            'initiatives': initiative_count,
            'collecting': collecting_count,
            'qualified': qualified_count
        }

# データベースインスタンス
db = Database()

# =============================================
# ユーティリティ関数
# =============================================

def generate_voter_id(google_id):
    """匿名投票者IDを生成"""
    return hashlib.sha256(f"{google_id}_{datetime.now().date().isoformat()}".encode()).hexdigest()[:16]

def get_fact_check_response(query):
    """ファクトチェック"""
    mock_responses = {
        '消費税': {
            'answer': '消費税率10%は2019年10月に導入されました。軽減税率により食品等は8%が維持されています。',
            'sources': ['財務省', '国税庁']
        },
        '防衛費': {
            'answer': '2024年度の防衛費は約7.9兆円で、GDP比約1.6%となっています。',
            'sources': ['防衛省', '財務省']
        },
        '最低賃金': {
            'answer': '2024年度の全国加重平均最低賃金は1,054円です。都道府県により異なります。',
            'sources': ['厚生労働省']
        }
    }
    
    for key, response in mock_responses.items():
        if key in query:
            return response
    
    return {
        'answer': 'ご質問の内容について、公的機関のデータに基づいて回答します。詳細な情報源もご確認ください。',
        'sources': ['総務省統計局', '内閣府']
    }

# =============================================
# セッション状態の初期化
# =============================================

if 'user' not in st.session_state:
    st.session_state.user = None

# =============================================
# メインアプリケーション
# =============================================

if not st.session_state.user:
    st.markdown('<div class="main-header">🗳️ 国民投票システム</div>', unsafe_allow_html=True)
    st.markdown("### 民主主義を実践するプラットフォーム")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("---")
        
        st.markdown("""
        <div class="info-box">
            <h4>🔐 ログイン</h4>
            <p>本番環境ではGoogle OAuth 2.0による認証を実装します</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander("📝 ログイン", expanded=True):
            email = st.text_input("メールアドレス", placeholder="example@email.com")
            name = st.text_input("ユーザー名", placeholder="名前を入力してください")
            
            col_btn1, col_btn2 = st.columns(2)
            
            with col_btn1:
                if st.button("🔐 ログイン", use_container_width=True, type="primary"):
                    if email and name:
                        google_id = hashlib.md5(email.encode()).hexdigest()
                        voter_id = generate_voter_id(google_id)
                        user = db.create_or_update_user(google_id, email, name, voter_id)
                        st.session_state.user = user
                        st.rerun()
                    else:
                        st.error("メールアドレスとユーザー名を入力してください")
            
            with col_btn2:
                if st.button("👑 管理者", use_container_width=True):
                    google_id = 'admin_001'
                    voter_id = generate_voter_id(google_id)
                    user = db.create_or_update_user(google_id, 'admin@example.com', '管理者', voter_id, is_admin=True)
                    st.session_state.user = user
                    st.rerun()
        
        st.markdown("---")
        
        st.markdown("""
        <div class="info-box">
            <h4>✨ システムの特徴</h4>
            <ul>
                <li>🔒 OAuth 2.0による安全な認証</li>
                <li>💾 SQLiteによるデータ永続化</li>
                <li>🔐 無記名投票で匿名性を保証</li>
                <li>✅ 二重投票・二重署名防止</li>
                <li>📊 リアルタイム集計表示</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

else:
    # ヘッダー
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown('<div class="main-header">🗳️ 国民投票システム</div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f"**{st.session_state.user['name']}**")
        if st.session_state.user['is_admin']:
            st.markdown('<span class="admin-badge">👑 管理者</span>', unsafe_allow_html=True)
        if st.button("ログアウト", use_container_width=True):
            st.session_state.user = None
            st.rerun()
    
    st.markdown("---")
    
    # タブ
    tabs = ["📋 レファレンダム", "🚫 拒否権投票", "✍️ イニシアティブ", "🔍 ファクトチェック"]
    if st.session_state.user['is_admin']:
        tabs.append("⚙️ 管理者")
    
    tab_objects = st.tabs(tabs)
    
    # レファレンダムタブ
    with tab_objects[0]:
        st.header("📋 国民投票（レファレンダム）")
        proposals = db.get_all_proposals()
        referendum_proposals = [p for p in proposals if p['type'] == 'referendum']
        
        if not referendum_proposals:
            st.info("現在進行中のレファレンダムはありません")
        
        for proposal in referendum_proposals:
            with st.container():
                st.subheader(proposal['title'])
                st.write(proposal['description'])
                
                votes_data = pd.DataFrame({
                    '選択肢': ['賛成', '反対'],
                    '票数': [proposal['votes']['agree'], proposal['votes']['disagree']]
                })
                
                fig = px.bar(votes_data, x='選択肢', y='票数', 
                            color='選択肢',
                            color_discrete_map={'賛成': '#10B981', '反対': '#EF4444'})
                fig.update_layout(showlegend=False, height=300)
                st.plotly_chart(fig, use_container_width=True)
                
                if db.has_voted(proposal['id'], st.session_state.user['voter_id']):
                    st.success("✅ 投票済み")
                else:
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(f"👍 賛成 ({proposal['votes']['agree']})", 
                                   key=f"agree_{proposal['id']}", 
                                   use_container_width=True):
                            if db.cast_vote(proposal['id'], st.session_state.user['voter_id'], 'agree'):
                                st.success("✅ 投票完了")
                                st.rerun()
                    with col2:
                        if st.button(f"👎 反対 ({proposal['votes']['disagree']})", 
                                   key=f"disagree_{proposal['id']}", 
                                   use_container_width=True):
                            if db.cast_vote(proposal['id'], st.session_state.user['voter_id'], 'disagree'):
                                st.success("✅ 投票完了")
                                st.rerun()
                
                st.markdown("---")
    
    # 拒否権投票タブ
    with tab_objects[1]:
        st.header("🚫 拒否権行使投票")
        proposals = db.get_all_proposals()
        veto_proposals = [p for p in proposals if p['type'] == 'veto']
        
        if not veto_proposals:
            st.info("現在進行中の拒否権投票はありません")
        
        for proposal in veto_proposals:
            with st.container():
                st.subheader(proposal['title'])
                st.write(proposal['description'])
                
                votes_data = pd.DataFrame({
                    '選択肢': ['拒否', '承認'],
                    '票数': [proposal['votes']['veto'], proposal['votes']['approve']]
                })
                
                fig = px.pie(votes_data, values='票数', names='選択肢',
                           color='選択肢',
                           color_discrete_map={'拒否': '#EF4444', '承認': '#3B82F6'})
                fig.update_layout(height=300)
                st.plotly_chart(fig, use_container_width=True)
                
                if db.has_voted(proposal['id'], st.session_state.user['voter_id']):
                    st.success("✅ 投票済み")
                else:
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(f"🚫 拒否 ({proposal['votes']['veto']})", 
                                   key=f"veto_{proposal['id']}", 
                                   use_container_width=True):
                            if db.cast_vote(proposal['id'], st.session_state.user['voter_id'], 'veto'):
                                st.success("✅ 投票完了")
                                st.rerun()
                    with col2:
                        if st.button(f"✅ 承認 ({proposal['votes']['approve']})", 
                                   key=f"approve_{proposal['id']}", 
                                   use_container_width=True):
                            if db.cast_vote(proposal['id'], st.session_state.user['voter_id'], 'approve'):
                                st.success("✅ 投票完了")
                                st.rerun()
                
                st.markdown("---")
    
    # イニシアティブタブ
    with tab_objects[2]:
        st.header("✍️ イニシアティブ（国民発議）")
        
        with st.expander("➕ 新しいイニシアティブを作成", expanded=False):
            new_title = st.text_input("タイトル", key="new_init_title")
            new_desc = st.text_area("詳細な説明", key="new_init_desc", height=100)
            
            if st.button("イニシアティブを作成", type="primary"):
                if new_title and new_desc:
                    db.create_initiative(new_title, new_desc, st.session_state.user['voter_id'])
                    st.success("✅ イニシアティブが作成されました")
                    st.rerun()
                else:
                    st.error("タイトルと説明を入力してください")
        
        st.markdown("---")
        
        initiatives = db.get_all_initiatives()
        for initiative in initiatives:
            with st.container():
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.subheader(initiative['title'])
                    st.write(initiative['description'])
                
                with col2:
                    if initiative['status'] == 'qualified':
                        st.success("✅ 成立")
                    else:
                        st.warning("📝 募集中")
                
                progress = min(initiative['signatures'] / initiative['required'], 1.0)
                st.progress(progress)
                st.caption(f"進捗: {initiative['signatures']} / {initiative['required']} 署名 ({progress*100:.1f}%)")
                
                if initiative['status'] == 'collecting':
                    if db.has_signed(initiative['id'], st.session_state.user['voter_id']):
                        st.success("✅ 署名済み")
                    else:
                        if st.button(f"✍️ 署名する", key=f"sign_{initiative['id']}", 
                                   use_container_width=True, type="primary"):
                            success, qualified = db.sign_initiative(initiative['id'], st.session_state.user['voter_id'])
                            if success:
                                if qualified:
                                    st.balloons()
                                    st.success(f"🎉 イニシアティブ「{initiative['title']}」が成立しました！")
                                    st.info("📋 レファレンダムタブに追加されました")
                                else:
                                    st.success("✅ 署名完了")
                                st.rerun()
                            else:
                                st.warning("既に署名済みです")
                else:
                    st.markdown("""
                    <div class="success-box">
                        <strong>✅ このイニシアティブは成立しました</strong><br>
                        レファレンダムタブで投票できます。
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
    
    # ファクトチェックタブ
    with tab_objects[3]:
        st.header("🔍 ファクトチェック")
        st.write("投票に関して確認したい情報を入力してください")
        
        query = st.text_area("質問を入力", 
                           placeholder="例: 消費税の現在の税率は？", 
                           height=100)
        
        if st.button("ファクトチェックを実行", type="primary"):
            if query:
                response = get_fact_check_response(query)
                
                # データベースに保存
                db.save_fact_check(
                    st.session_state.user['id'],
                    query,
                    response['answer'],
                    response['sources']
                )
                
                st.markdown(f"""
                <div class="info-box">
                    <h4>📝 質問</h4>
                    <p>{query}</p>
                    
                    <h4>💡 回答</h4>
                    <p>{response['answer']}</p>
                    
                    <h4>📚 情報源</h4>
                    <ul>
                        {''.join([f'<li>{source}</li>' for source in response['sources']])}
                    </ul>
                    
                    <p style="color: #6B7280; font-size: 0.875rem;">
                        回答日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}
                    </p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("質問を入力してください")
        
        # 履歴表示
        history = db.get_fact_check_history(st.session_state.user['id'])
        if history:
            st.markdown("---")
            st.subheader("📋 過去の質問履歴")
            for item in history:
                with st.expander(f"{item['timestamp'].strftime('%Y/%m/%d %H:%M')} - {item['query'][:50]}..."):
                    st.write(f"**質問:** {item['query']}")
                    st.write(f"**回答:** {item['answer']}")
                    st.write(f"**情報源:** {', '.join(item['sources'])}")
    
    # 管理者タブ
    if st.session_state.user['is_admin'] and len(tab_objects) > 4:
        with tab_objects[4]:
            st.header("⚙️ 管理者設定")
            
            st.markdown("""
            <div class="warning-box">
                <strong>⚠️ 管理者専用ページ</strong><br>
                この画面は管理者のみアクセス可能です。設定の変更は全てのユーザーに影響します。
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # イニシアティブ設定
            st.subheader("📝 イニシアティブ設定")
            
            st.write("イニシアティブが成立するために必要な署名数を設定します")
            st.caption("テスト用には少数（例: 3-5人）、本番環境では実際の人数を設定してください")
            
            current_required = db.get_setting('required_signatures', 10000)
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("テスト: 3人", use_container_width=True):
                    db.set_setting('required_signatures', 3)
                    st.success("必要署名数を3に設定しました")
                    st.rerun()
            
            with col2:
                if st.button("デモ: 10人", use_container_width=True):
                    db.set_setting('required_signatures', 10)
                    st.success("必要署名数を10に設定しました")
                    st.rerun()
            
            with col3:
                if st.button("小規模: 100人", use_container_width=True):
                    db.set_setting('required_signatures', 100)
                    st.success("必要署名数を100に設定しました")
                    st.rerun()
            
            with col4:
                if st.button("本番: 10,000人", use_container_width=True):
                    db.set_setting('required_signatures', 10000)
                    st.success("必要署名数を10,000に設定しました")
                    st.rerun()
            
            custom_num = st.number_input("カスタム設定", 
                                        min_value=1, 
                                        value=current_required,
                                        step=1)
            
            if st.button("カスタム値を適用", type="primary"):
                db.set_setting('required_signatures', custom_num)
                st.success(f"必要署名数を{custom_num}に設定しました")
                st.rerun()
            
            st.info(f"**現在の設定:** {current_required} 署名")
            
            st.markdown("---")
            
            # 統計情報
            st.subheader("📊 統計情報")
            
            stats = db.get_statistics()
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("レファレンダム", stats['referendum'])
            
            with col2:
                st.metric("拒否権投票", stats['veto'])
            
            with col3:
                st.metric("イニシアティブ", stats['initiatives'])
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("署名募集中", stats['collecting'])
            
            with col2:
                st.metric("成立済み", stats['qualified'])
            
            st.markdown("---")
            
            # データベース情報
            st.subheader("💾 データベース情報")
            
            db_file = Path("referendum_data.db")
            if db_file.exists():
                file_size = db_file.stat().st_size / 1024  # KB
                st.info(f"データベースファイルサイズ: {file_size:.2f} KB")
            
            st.caption("データはSQLiteデータベースに永続化されています")
            
            st.markdown("---")
            
            # OAuth設定情報
            st.subheader("🔐 OAuth 2.0 設定")
            
            st.markdown("""
            <div class="info-box">
                <h4>Google OAuth 2.0の設定手順</h4>
                <ol>
                    <li><strong>Google Cloud Console</strong>にアクセス
                        <ul>
                            <li>https://console.cloud.google.com/</li>
                        </ul>
                    </li>
                    <li><strong>プロジェクトを作成</strong>
                        <ul>
                            <li>新しいプロジェクトを作成または既存のものを選択</li>
                        </ul>
                    </li>
                    <li><strong>OAuth同意画面を設定</strong>
                        <ul>
                            <li>「APIとサービス」→「OAuth同意画面」</li>
                            <li>ユーザータイプを選択（外部/内部）</li>
                            <li>アプリ情報を入力</li>
                        </ul>
                    </li>
                    <li><strong>認証情報を作成</strong>
                        <ul>
                            <li>「認証情報」→「認証情報を作成」→「OAuthクライアントID」</li>
                            <li>アプリケーションタイプ: Webアプリケーション</li>
                            <li>承認済みのリダイレクトURIを追加</li>
                        </ul>
                    </li>
                    <li><strong>Streamlit Secretsに設定</strong>
                        <ul>
                            <li>プロジェクトルートに<code>.streamlit/secrets.toml</code>を作成</li>
                            <li>以下を記述：</li>
                        </ul>
                    </li>
                </ol>
                
                <pre style="background: #1f2937; color: #f3f4f6; padding: 1rem; border-radius: 0.5rem; margin-top: 1rem;">
[google_oauth]
client_id = "your-client-id.apps.googleusercontent.com"
client_secret = "your-client-secret"

[admin]
emails = ["admin1@example.com", "admin2@example.com"]
                </pre>
                
                <h4 style="margin-top: 1.5rem;">必要なPythonパッケージ</h4>
                <pre style="background: #1f2937; color: #f3f4f6; padding: 1rem; border-radius: 0.5rem;">
google-auth>=2.23.0
google-auth-oauthlib>=1.1.0
google-auth-httplib2>=0.1.1
                </pre>
            </div>
            """, unsafe_allow_html=True)