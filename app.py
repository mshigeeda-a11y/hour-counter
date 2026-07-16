import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="授業時数カウントアプリ", layout="wide")
st.title("🏫 授業時数集計アプリ (月別ファイル結合版)")

# ファイル名から学年クラス（例: 高2D, 中1A）を割り出す関数
def parse_class_name(filename):
    match = re.match(r'^\d+_(\d+)_(\d+)_([A-Za-z]+)', filename)
    if match:
        school_type_flag = match.group(1) # 0なら中学、1なら高校
        grade = match.group(2)            # 学年
        cls = match.group(3).upper()      # クラス
        
        school_type = "高" if school_type_flag == "1" else "中"
        return f"{school_type}{grade}{cls}"
    else:
        return filename.replace(".csv", "")

# 「4/1」「05/01」「5/1」などから日付オブジェクトを作る関数
def to_datetime(date_str):
    if pd.isna(date_str) or str(date_str).strip().lower() == 'nan':
        return None, None
    
    cleaned = str(date_str).strip()
    match = re.search(r'(\d+)\s*/\s*(\d+)', cleaned)
    if match:
        try:
            month = int(match.group(1))
            day = int(match.group(2))
            
            # 4月〜12月は2026年、1月〜3月は2027年としてカレンダー順を維持
            year = 2026 if month >= 4 else 2027
            
            formatted_str = f"{month:02d}/{day:02d}"
            dt = pd.to_datetime(f"{year}/{formatted_str}", format="%Y/%m/%d")
            return dt, formatted_str
        except:
            return None, None
    return None, None

# 複数ファイルアップロード
uploaded_files = st.file_uploader(
    "4月・5月・6月などのCSVファイルをまとめてアップロードしてください", 
    type=["csv"], 
    accept_multiple_files=True
)

if uploaded_files:
    try:
        all_dates_dict = {} 
        
        # クラスごとのデータを溜める辞書
        class_columns_dict = {}

        # --- 1. アップロードされた全ファイルを解析し、クラスごとに列データを「結合」する ---
        for file in uploaded_files:
            class_name = parse_class_name(file.name)
            
            try:
                df_raw = pd.read_csv(file, header=None, encoding='utf-8')
            except UnicodeDecodeError:
                file.seek(0)
                df_raw = pd.read_csv(file, header=None, encoding='cp932')
            
            dates = df_raw.iloc[0].ffill().values  # 1行目の日付
            periods = df_raw.iloc[2].values       # 3行目の時限
            student_data = df_raw.iloc[3:]         # 4行目以降の生徒データ
            
            if class_name not in class_columns_dict:
                class_columns_dict[class_name] = []
                
            # このファイルの全列を1列ずつバラして保管
            for col_idx in range(len(df_raw.columns)):
                d_val = dates[col_idx]
                dt, f_str = to_datetime(d_val)
                
                if f_str and dt:
                    all_dates_dict[f_str] = dt
                    
                # 1列分の情報を辞書にまとめる
                col_info = {
                    "dt": dt,
                    "date_str": f_str,
                    "period": periods[col_idx],
                    "cells": student_data[col_idx]
                }
                class_columns_dict[class_name].append(col_info)
        
        # 選択肢として使う全日程の一覧をソート
        sorted_display_dates = sorted(all_dates_dict.keys(), key=lambda x: all_dates_dict[x])
        
        # --- 2. サイドバーの設定 ---
        st.sidebar.header("🗓️ 期間指定")
        start_date_str = st.sidebar.selectbox("開始日", sorted_display_dates, index=0)
        end_date_str = st.sidebar.selectbox("終了日", sorted_display_dates, index=len(sorted_display_dates)-1)
        
        st.sidebar.write("---")
        st.sidebar.header("🏫 表示クラス選択")
        available_classes = sorted(list(class_columns_dict.keys()))
        selected_class = st.sidebar.selectbox("集計を見たいクラスを選んでください", available_classes)
        
        start_dt = all_dates_dict[start_date_str]
        end_dt = all_dates_dict[end_date_str]
        
        if start_dt > end_dt:
            st.error("エラー: 開始日は終了日より前の日付を選択してください。")
        else:
            # --- 3. 選択されたクラスの合算データを集計 (修正版) ---
            all_cols_for_class = class_columns_dict[selected_class]
            
            subject_counts = {}
            subject_dates = {}
            
            # 溜め込まれた全ファイルをまたぐ列データをループ処理
            for col_info in all_cols_for_class:
                current_dt = col_info["dt"]
                date_display_str = col_info["date_str"]
                period_str = str(col_info["period"]).strip()
                col_cells = col_info["cells"]
                
                # 日付がない、または時限が未入力、またはSHRの場合は除外
                if current_dt is None or pd.isna(col_info["period"]) or period_str == "SHR":
                    continue
                    
                # 指定された期間内かチェック
                if start_dt <= current_dt <= end_dt:
                    col_cells_clean = col_cells.dropna()
                    col_cells_str = col_cells_clean.astype(str)
                    
                    # 【改善】「HR」または「思索」の場合：
                    # 生徒の入力内容にかかわらず、枠が存在していれば確実に1コマとしてカウントする
                    if period_str in ["HR", "思索"]:
                        detected_subject = period_str
                        subject_counts[detected_subject] = subject_counts.get(detected_subject, 0) + 1
                        if detected_subject not in subject_dates:
                            subject_dates[detected_subject] = set()
                        subject_dates[detected_subject].add(date_display_str)
                        continue  # HR/思索の処理はここで完了、次の列へ進む
                    
                    # 通常の授業時（1〜7限など）の判定
                    valid_cells = col_cells_str[col_cells_str.str.contains(':|：|出席|欠席|遅刻', na=False)]
                    
                    if len(valid_cells) > 0:
                        detected_subjects_in_col = set()
                        
                        for cell_val in valid_cells:
                            # 半角・全角のコロン等で区切られたパーツに分解
                            parts = re.split(r'[:：|｜\s]+', cell_val)
                            for p in parts:
                                p_clean = p.strip()
                                
                                # 「出欠 1回目」や「出席」などのステータス文字、不要な空文字を除外して教科名だけを抽出
                                if p_clean:
                                    # 「出席」や「欠席」という言葉自体を含むパーツ（出欠表記）は教科名から除外
                                    if re.search(r'(出席|欠席|遅刻|公欠|忌引|見学)', p_clean):
                                        continue
                                    if p_clean.lower() in ['nan', 'am', 'pm']:
                                        continue
                                    
                                    detected_subjects_in_col.add(p_clean)
                        
                        # もし「教科」が一つも見つからなかった通常の時限
                        if len(detected_subjects_in_col) == 0:
                            detected_subjects_in_col.add(f"{period_str}限")
                        
                        # カウントと日付の記録
                        for detected_subject in detected_subjects_in_col:
                            subject_counts[detected_subject] = subject_counts.get(detected_subject, 0) + 1
                            
                            if detected_subject not in subject_dates:
                                subject_dates[detected_subject] = set()
                            subject_dates[detected_subject].add(date_display_str)
            
            # --- 4. 結果の表示 ---
            st.header(f"📊 【{selected_class}】 総合集計結果 ({start_date_str} 〜 {end_date_str})")
            
            if subject_counts:
                st.subheader("📋 教科名 ： 授業数 ： 授業した日付")
                
                result_texts = []
                for subj in sorted(subject_counts.keys()):
                    count = subject_counts[subj]
                    sorted_dates = sorted(list(subject_dates[subj]), key=lambda x: all_dates_dict[x])
                    dates_list = ", ".join(sorted_dates)
                    
                    line_text = f"**{subj}** ： {count}コマ ： {dates_list}"
                    result_texts.append(line_text)
                    
                    st.markdown(f"🔹 {line_text}")
                
                st.write("---")
                st.subheader(f"👇 【{selected_class}】 コピペ用テキスト")
                raw_text = f"--- {selected_class} 集計 ({start_date_str}～{end_date_str}) ---\n"
                raw_text += "\n".join([t.replace("**", "") for t in result_texts])
                st.text_area("以下の枠内からコピーできます", value=raw_text, height=250)

            else:
                st.info(f"{selected_class} の指定された期間内に授業データが見つかりませんでした。")
                
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")
