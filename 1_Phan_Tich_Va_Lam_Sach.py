import pandas as pd

# TIỀN XỬ LÝ DỮ LIỆU

print("Đang nạp dữ liệu từ 'spotify.csv'...")
df = pd.read_csv('spotify.csv')

# --- 2.1. Kiểm tra trước khi làm sạch ---
print("\n--- 2.1. Kiểm tra kích thước và kiểu dữ liệu ---")
print(df.info())
print("\nĐếm tổng số giá trị rỗng ở từng cột:")
print(df.isnull().sum())

# --- 2.2 & 2.3. Quá trình làm sạch dữ liệu ---
print("\nĐang tiến hành dọn rác và lọc trùng lặp...")

# 1. Xóa cột index dư thừa (Unnamed: 0) nếu có
df = df.drop(columns=['Unnamed: 0'], errors='ignore')

# 2. Xóa các dòng chứa giá trị rỗng (NaN)
df = df.dropna()

# --- 3. Gộp nhóm đa nhãn (Multi-genre) theo track_id ---
# Giúp giữ lại đầy đủ tất cả các thể loại nhạc của bài hát thay vì bị xóa mất
if 'track_genre' in df.columns:
    df = df.groupby('track_id').agg({
        **{col: 'first' for col in df.columns if col not in ['track_id', 'track_genre']},
        'track_genre': lambda x: ', '.join(x.dropna().unique())
    }).reset_index()
else:
    df = df.drop_duplicates(subset=['track_id'])


# --- 2.5. Tạo biến phái sinh ---
# Chuyển đổi cột duration_ms sang phút (duration_min) để dễ phân tích
df['duration_min'] = (df['duration_ms'] / 60000).round(2)


# --- 2.4. Kết quả sau tiền xử lý ---
print("\n--- 2.4. Kết quả sau tiền xử lý ---")
print(f"Kích thước dữ liệu sau khi làm sạch: {df.shape}")
# Lấy ra giá trị rỗng cao nhất (nếu bằng 0 nghĩa là tập data đã sạch hoàn toàn)
print(f"Số lượng giá trị rỗng còn lại: {df.isnull().sum().max()}")


# --- XUẤT RA FILE SẠCH ---
output_file = 'spotify_cleaned.csv'
df.to_csv(output_file, index=False)
print(f"\n✅ THÀNH CÔNG! Đã lưu tập dữ liệu sạch ra file: {output_file}")
print("Từ bây giờ, hãy dùng file này cho các bước vẽ biểu đồ tiếp theo!")