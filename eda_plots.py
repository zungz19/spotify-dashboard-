import pandas as pd
import plotly.express as px
import plotly.graph_objects as go 

# NẠP DỮ LIỆU ĐÃ LÀM SẠCH
df = pd.read_csv('spotify_cleaned.csv')

# BIỂU ĐỒ 3.1: HISTOGRAM POPULARITY
mean_val = df['popularity'].mean()
median_val = df['popularity'].median()

fig_hist = px.histogram(
    df, 
    x='popularity', 
    nbins=30,
    title='Hình 3.1: Biểu đồ Histogram thể hiện phân phối Điểm phổ biến (Popularity)',
    color_discrete_sequence=['#1DB954'] 
)

fig_hist.add_vline(x=median_val, line_width=2, line_color="black", 
                   annotation_text=f"Median: {median_val:.0f}", annotation_position="top left")
fig_hist.add_vline(x=mean_val, line_dash="dash", line_width=2, line_color="red", 
                   annotation_text=f"Mean: {mean_val:.2f}", annotation_position="top right")

fig_hist.update_layout(
    xaxis_title="Điểm phổ biến (Popularity Score)",
    yaxis_title="Tần suất (Số lượng bài hát)",
    plot_bgcolor='white'
)
fig_hist.show()



# BIỂU ĐỒ 3.2: BIỂU ĐỒ NHIỆT MẬT ĐỘ (DENSITY HEATMAP)
fig_density = px.density_heatmap(
    df, 
    x='energy', 
    y='danceability',
    nbinsx=50, 
    nbinsy=50,
    color_continuous_scale='Viridis',
    title='Hình 3.2: Biểu đồ nhiệt mật độ 2 chiều giữa Cường độ âm thanh và Tính khiêu vũ'
)
fig_density.update_layout(
    xaxis_title="Cường độ âm thanh (Energy)",
    yaxis_title="Tính khiêu vũ (Danceability)",
    plot_bgcolor='white'
)
fig_density.show()



# BIỂU ĐỒ 3.3: MA TRẬN NHIỆT (HEATMAP)
# Chọn các cột số để tính tương quan
numeric_cols = [
    'popularity', 'danceability', 'energy', 'loudness', 
    'speechiness', 'acousticness', 'instrumentalness', 
    'liveness', 'valence', 'tempo', 'duration_min'
]

# Tính ma trận Pearson
corr_matrix = df[numeric_cols].corr(method='pearson')

fig_heatmap = px.imshow(
    corr_matrix,
    text_auto='.3f',
    aspect="auto",
    color_continuous_scale='RdBu_r',
    title='Hình 3.3: Ma trận tương quan (Heatmap) giữa các đặc trưng âm thanh',
    labels=dict(color="Hệ số Pearson (r)")
)

fig_heatmap.update_layout(
    xaxis_title="",
    yaxis_title="",
    plot_bgcolor='white',
    width=800,
    height=800
)
fig_heatmap.show()


# BIỂU ĐỒ 3.4: RADAR CHART 
# Chọn 6 đặc trưng âm thanh để tạo thành hình lục giác trên Radar Chart
features = ['danceability', 'energy', 'valence', 'acousticness', 'speechiness', 'liveness']

# Tách nhóm và tính giá trị trung bình
hit_mean = df[df['popularity'] >= 80][features].mean().tolist()
flop_mean = df[df['popularity'] <= 20][features].mean().tolist()

# copy giá trị đầu tiên chèn vào cuối cùng để khép kín vòng lưới
features_closed = features + [features[0]]
hit_mean_closed = hit_mean + [hit_mean[0]]
flop_mean_closed = flop_mean + [flop_mean[0]]

# Khởi tạo biểu đồ
fig_radar = go.Figure()

# Vẽ màng nhện cho Siêu Hit (Màu xanh)
fig_radar.add_trace(go.Scatterpolar(
    r=hit_mean_closed,
    theta=features_closed,
    fill='toself',
    name='Siêu Hit (Popularity ≥ 80)',
    line_color='#1DB954',
    opacity=0.8
))

# Vẽ màng nhện cho Nhạc Flop (Màu đỏ)
fig_radar.add_trace(go.Scatterpolar(
    r=flop_mean_closed,
    theta=features_closed,
    fill='toself',
    name='Nhạc Flop (Popularity ≤ 20)',
    line_color='#E91E63',
    opacity=0.7
))

# Căn chỉnh giao diện nền trắng, lưới xám
fig_radar.update_layout(
    title=dict(
        text='Hình 3.4: Radar Chart so sánh cấu trúc âm thanh của bài Hit và bài Flop',
        x=0.5,
        font=dict(size=16)
    ),
    polar=dict(
        radialaxis=dict(
            visible=True,
            range=[0, 0.75], # Giới hạn trục từ 0 đến 0.75 cho vừa vặn với số liệu
            gridcolor='lightgray',
            linecolor='lightgray'
        ),
        angularaxis=dict(
            gridcolor='lightgray',
            linecolor='lightgray'
        ),
        bgcolor='white'
    ),
    plot_bgcolor='white',
    paper_bgcolor='white',
    showlegend=True,
    legend=dict(orientation="h", y=-0.1, x=0.2) 
)
fig_radar.show()


# BIỂU ĐỒ 3.5: BOXPLOT SO SÁNH THỜI LƯỢNG
df_hit = df[df['popularity'] >= 80].copy()
df_hit['Nhóm'] = 'Siêu Hit (Popularity ≥ 80)'
df_flop = df[df['popularity'] <= 20].copy()
df_flop['Nhóm'] = 'Nhạc Flop (Popularity ≤ 20)'
df_box = pd.concat([df_hit, df_flop])

fig_box = px.box(
    df_box, 
    x="Nhóm", 
    y="duration_min", 
    color="Nhóm",
    title='Hình 3.5: So sánh phân phối thời lượng bài hát: Siêu Hit vs Nhạc Flop',
    points="outliers",
    color_discrete_map={'Siêu Hit (Popularity ≥ 80)': '#1DB954', 'Nhạc Flop (Popularity ≤ 20)': '#E91E63'}
)
fig_box.update_layout(
    yaxis_title="Thời lượng (Phút)",
    xaxis_title="",
    plot_bgcolor='white'
)
fig_box.show()


# BIỂU ĐỒ 3.6: SO SÁNH POPULARITY THEO NHÃN EXPLICIT
fig_explicit = px.box(
    df,
    x="explicit",
    y="popularity",
    color="explicit",
    title='Hình 3.6: Phân phối Điểm phổ biến theo Nhãn kiểm duyệt (Explicit)',
    color_discrete_map={True: '#E91E63', False: '#1DB954'},
    labels={"explicit": "Nhãn Explicit (Ngôn từ mạnh)", "popularity": "Điểm phổ biến"}
)
fig_explicit.update_layout(plot_bgcolor='white', xaxis_title="Nhãn Explicit", yaxis_title="Điểm phổ biến")
fig_explicit.show()