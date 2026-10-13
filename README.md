# Bài tập lớn: Trực quan hóa Dữ liệu: Phân tích và trực quan hóa mối quan hệ giữa các đặc trưng âm thanh và mức độ phổ biến của bài hát trên Spotify.


## 📂 Cấu trúc thư mục
- `main.py`: Mã nguồn chính xây dựng giao diện Web Dashboard bằng Streamlit.
- `1_Phan_Tich_Va_Lam_Sach.py`: Script tiền xử lý, làm sạch dữ liệu và xử lý đa nhãn.
- `eda_plots.py`: Các hàm hỗ trợ trực quan hóa biểu đồ phân tích khám phá (EDA).
- `spotify_cleaned.csv`: Tệp dữ liệu đã được làm sạch, được sinh ra khi chạy file 1_Phan_Tich_Va_Lam_Sach.py
- `spotify.csv`: Tệp dữ liệu gốc 

## Hướng dẫn cài đặt và chạy ứng dụng

### 1. Cài đặt các thư viện cần thiết
Mở terminal tại thư mục dự án và chạy lệnh:
```bash
pip install streamlit pandas plotly

### 2. Chạy script 1_Phan_Tich_Va_Lam_Sach.py để sinh ra tệp spotify_cleaned.csv
python 1_Phan_Tich_Va_Lam_Sach.py

### 3. Khởi chạy Web Dashboard
streamlit run main.py 