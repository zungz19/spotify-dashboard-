import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# 1. CẤU HÌNH GIAO DIỆN
st.set_page_config(
    page_title="Mối liên hệ giữa Đặc trưng âm thanh và mức độ phổ biến của bài hát trên Spotify",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Nạp dữ liệu sạch
@st.cache_data
def load_data():
    return pd.read_csv('spotify_cleaned.csv')

df = load_data()


# 2. THANH SIDEBAR: BỘ LỌC TOÀN CỤC (GLOBAL FILTERS)

st.sidebar.markdown("<h2 style='color: #1DB954;'>🎛️ BẢNG ĐIỀU KHIỂN</h2>", unsafe_allow_html=True)
st.sidebar.markdown("---")

st.sidebar.markdown("### 🔍 Bộ lọc dữ liệu")

# 2.1. Bộ lọc 1: Chọn Thể loại nhạc (Genre)
# LỌC VÀ LÀM SẠCH DANH SÁCH THỂ LOẠI CHO SIDEBAR
# 2.1.1. Tách tất cả các chuỗi thể loại bị gộp (nếu có) bằng dấu phẩy, sau đó xóa khoảng trắng thừa
all_genres_raw = df['track_genre'].dropna().str.split(',').tolist()
flattened_genres = [genre.strip() for sublist in all_genres_raw for genre in sublist]

# 2.1.2. Đếm tần suất xuất hiện của từng thể loại đơn lẻ
genre_counts = pd.Series(flattened_genres).value_counts()

# 2.1.3. Chỉ giữ lại các thể loại có từ 5 bài hát trở lên (loại bỏ các thể loại rác chỉ có 1 bài)
valid_genres = genre_counts[genre_counts >= 5].index.tolist()
all_genres = sorted(valid_genres)

selected_genre = st.sidebar.selectbox(
    "Chọn thể loại nhạc (Genre):", 
    options=["Tất cả (All)"] + all_genres
)

# 2.2. Bộ lọc 2: Khoảng điểm phổ biến
min_pop = int(df['popularity'].min())
max_pop = int(df['popularity'].max())
selected_pop_range = st.sidebar.slider(
    "Khoảng điểm phổ biến (Popularity):",
    min_value=min_pop,
    max_value=max_pop,
    value=(min_pop, max_pop)
)
# THỰC HIỆN LỌC DỮ LIỆU DỰA TRÊN THANH SIDEBAR
filtered_df = df.copy()
if selected_genre != "Tất cả (All)":
    filtered_df = filtered_df[filtered_df['track_genre'].str.split(', ').apply(lambda g: selected_genre in g)]

filtered_df = filtered_df[
    (filtered_df['popularity'] >= selected_pop_range[0]) & 
    (filtered_df['popularity'] <= selected_pop_range[1])
]

st.sidebar.markdown("---")
st.sidebar.info(f"📊 Đang hiển thị **{len(filtered_df):,}** / {len(df):,} bản ghi thỏa mãn điều kiện lọc.")



# 3. HEADER & HÀNG THẺ KPI (METRICS CARDS)
st.markdown("<h1 style='color: #1DB954;'>🎵 Dashboard: Mối liên hệ giữa đặc trưng âm thanh và mức độ phổ biến của bài hát trên Spotify</h1>", unsafe_allow_html=True)
st.markdown("Khám phá mối quan hệ cấu trúc âm thanh và mức độ phổ biến trên nền tảng streaming.")

# 3.1. Tính toán các chỉ số KPI theo dữ liệu đã lọc
total_tracks = len(filtered_df)
avg_popularity = filtered_df['popularity'].mean() if total_tracks > 0 else 0
avg_duration = filtered_df['duration_min'].mean() if total_tracks > 0 else 0
avg_energy = filtered_df['energy'].mean() if total_tracks > 0 else 0

# 3.2. Hiển thị 4 cột KPI 
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric(label="🎧 Tổng số bài hát", value=f"{total_tracks:,}")
kpi2.metric(label="⭐ Điểm phổ biến TB", value=f"{avg_popularity:.2f} / 100")
kpi3.metric(label="⏱️ Thời lượng TB", value=f"{avg_duration:.2f} phút")
kpi4.metric(label="⚡ Cường độ (Energy) TB", value=f"{avg_energy:.2f}")

st.markdown("---")



# 4. KHU VỰC HIỂN THỊ BIỂU ĐỒ (LAYOUT 2 CỘT)
if total_tracks == 0:
    st.warning(" Không tìm thấy bài hát nào phù hợp với bộ lọc hiện tại. Vui lòng chọn lại tiêu chí ở Sidebar!")
else:
    col1, col2 = st.columns(2)

    with col1:
        # BIỂU ĐỒ 1: HISTOGRAM POPULARITY
        st.subheader("1. Phân phối Điểm phổ biến (Popularity)")
        mean_val = filtered_df['popularity'].mean()
        median_val = filtered_df['popularity'].median()

        fig_hist = px.histogram(
            filtered_df, 
            x='popularity', 
            nbins=30,
            color_discrete_sequence=['#1DB954']
        )
        fig_hist.add_vline(x=median_val, line_width=2, line_color="#FFFFFF", annotation_text=f"Median: {median_val:.0f}", annotation_position="top left")
        fig_hist.add_vline(x=mean_val, line_dash="dash", line_width=2, line_color="#FF4B4B", annotation_text=f"Mean: {mean_val:.2f}", annotation_position="top right")
        fig_hist.update_layout(xaxis_title="Điểm phổ biến", yaxis_title="Tần suất", margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_hist, use_container_width=True, theme="streamlit")

        # BIỂU ĐỒ 3: MA TRẬN TƯƠNG QUAN
        st.subheader("3. Ma trận tương quan đặc trưng âm thanh")
        numeric_cols = ['popularity', 'danceability', 'energy', 'loudness', 'speechiness', 'acousticness', 'instrumentalness', 'liveness', 'valence', 'tempo', 'duration_min']
        
        # Tránh lỗi nếu dữ liệu lọc quá ít không tính được tương quan
        if len(filtered_df) > 5:
            corr_matrix = filtered_df[numeric_cols].corr(method='pearson')
            fig_heatmap = px.imshow(corr_matrix, text_auto='.2f', aspect="auto", color_continuous_scale='Tealrose', zmin=-1, zmax=1)
            fig_heatmap.update_layout(margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_heatmap, use_container_width=True, theme="streamlit")
        else:
            st.info("Cần ít nhất 5 bài hát để tính toán ma trận tương quan.")

    with col2:
        # BIỂU ĐỒ 2: DENSITY HEATMAP (Thay cho Scatter Plot)
        st.subheader("2. Mật độ tương quan Energy & Danceability")
        fig_density = px.density_heatmap(
            filtered_df, 
            x='energy', 
            y='danceability',
            nbinsx=40, nbinsy=40,
            color_continuous_scale='Viridis'
        )
        fig_density.update_layout(xaxis_title="Cường độ âm thanh (Energy)", yaxis_title="Tính khiêu vũ (Danceability)", margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_density, use_container_width=True, theme="streamlit")

        # BIỂU ĐỒ 4: RADAR CHART
        st.subheader("4. Audio Profile: Siêu Hit vs Flop")
        features = ['danceability', 'energy', 'valence', 'acousticness', 'speechiness', 'liveness']
        
        hit_df = filtered_df[filtered_df['popularity'] >= 80]
        flop_df = filtered_df[filtered_df['popularity'] <= 20]

        hit_mean = hit_df[features].mean().tolist() if len(hit_df) > 0 else [0]*6
        flop_mean = flop_df[features].mean().tolist() if len(flop_df) > 0 else [0]*6

        features_closed = features + [features[0]]
        hit_mean_closed = hit_mean + [hit_mean[0]]
        flop_mean_closed = flop_mean + [flop_mean[0]]

        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(r=hit_mean_closed, theta=features_closed, fill='toself', name=f'Siêu Hit (n={len(hit_df)})', line_color='#1DB954', opacity=0.8))
        fig_radar.add_trace(go.Scatterpolar(r=flop_mean_closed, theta=features_closed, fill='toself', name=f'Flop (n={len(flop_df)})', line_color='#FF4B4B', opacity=0.6))

        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 1], gridcolor='#444444', linecolor='#444444'),
                angularaxis=dict(gridcolor='#444444', linecolor='#444444'),
                bgcolor='rgba(0,0,0,0)'
            ),
            showlegend=True,
            legend=dict(orientation="h", y=-0.2, x=0.1),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig_radar, use_container_width=True, theme="streamlit")

    # BIỂU ĐỒ 5: BOXPLOT THỜI LƯỢNG (Chèn thêm ở dưới cùng)
    st.markdown("---")
    st.subheader("5. Phân phối thời lượng bài hát: Siêu Hit vs Flop")
    
    hit_df_box = filtered_df[filtered_df['popularity'] >= 80].copy()
    hit_df_box['Nhóm'] = 'Siêu Hit (≥ 80)'
    flop_df_box = filtered_df[filtered_df['popularity'] <= 20].copy()
    flop_df_box['Nhóm'] = 'Flop (≤ 20)'
    
    if not hit_df_box.empty and not flop_df_box.empty:
        df_box = pd.concat([hit_df_box, flop_df_box])
        fig_box = px.box(
            df_box, 
            x="Nhóm", 
            y="duration_min", 
            color="Nhóm",
            points="outliers",
            color_discrete_map={'Siêu Hit (≥ 80)': '#1DB954', 'Flop (≤ 20)': '#FF4B4B'}
        )
        fig_box.update_layout(yaxis_title="Thời lượng (Phút)", xaxis_title="", margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_box, use_container_width=True, theme="streamlit")
    else:
        st.info("Không đủ dữ liệu để vẽ biểu đồ so sánh thời lượng trong bộ lọc này.")


    # BIỂU ĐỒ 6: TÁC ĐỘNG CỦA NHÃN EXPLICIT
    st.markdown("---")
    st.subheader("6. Tác động của nhãn Explicit đến độ phổ biến")
    fig_explicit = px.box(
        filtered_df,
        x="explicit",
        y="popularity",
        color="explicit",
        color_discrete_map={True: '#FF4B4B', False: '#1DB954'},
        labels={"explicit": "Nhãn Explicit (Ngôn từ mạnh)", "popularity": "Điểm phổ biến"}
    )
    fig_explicit.update_layout(margin=dict(l=0, r=0, t=30, b=0), xaxis_title="Nhãn Explicit", yaxis_title="Điểm phổ biến")
    st.plotly_chart(fig_explicit, use_container_width=True, theme="streamlit")