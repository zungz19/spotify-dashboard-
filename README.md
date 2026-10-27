# Bài tập lớn Trực quan hóa Dữ liệu: Phân tích và trực quan hóa mối quan hệ giữa các đặc trưng âm thanh và mức độ phổ biến của bài hát trên Spotify

Dashboard trực tuyến: https://sr9mjlwiamzaoxsyuxp2hx.streamlit.app/

## 📂 Cấu trúc thư mục
- `main.py`: Mã nguồn chính xây dựng giao diện Web Dashboard bằng Streamlit.
- `1_Phan_Tich_Va_Lam_Sach.py`: Script tiền xử lý, làm sạch dữ liệu và xử lý đa nhãn.
- `eda_plots.py`: Mã nguồn vẽ các biểu đồ phân tích khám phá (EDA) dùng trong báo cáo.
- `spotify_cleaned.csv`: Tệp dữ liệu đã được làm sạch, được sinh ra khi chạy file `1_Phan_Tich_Va_Lam_Sach.py`.
- `spotify.csv`: Tệp dữ liệu gốc. Tệp này không kèm trong repo vì dung lượng lớn; tải tại [Kaggle – Spotify Dataset 114k Songs](https://www.kaggle.com/datasets/priyamchoksi/spotify-dataset-114k-songs), đổi tên thành `spotify.csv` (nếu tên khác) và đặt cùng thư mục với các file `.py`.

## Hướng dẫn cài đặt và chạy ứng dụng

### 1. Cài đặt các thư viện cần thiết
```bash
pip install -r requirements.txt
```

### 2. Làm sạch dữ liệu (sinh ra tệp spotify_cleaned.csv)
```bash
python 1_Phan_Tich_Va_Lam_Sach.py
```

### 3. Khởi chạy Web Dashboard
```bash
streamlit run main.py
```
