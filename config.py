"""Cấu hình chung cho toàn bộ pipeline và dashboard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # Tầng landing: lưu nguyên trạng HTML/JSON tải về
EXPORT_DIR = DATA_DIR / "export"      # Bản sao CSV của các bảng mart (để nộp kèm / làm báo cáo)
DB_PATH = DATA_DIR / "warehouse.duckdb"
LOCK_PATH = DATA_DIR / ".pipeline.lock"

# --- Thị trường cần thu thập (mã quốc gia theo Kworb) ---
MARKETS = {
    "vn": "Việt Nam",
    "global": "Toàn cầu",
}

# --- Nguồn 1: Kworb (bảng xếp hạng Spotify) ---
KWORB_BASE = "https://kworb.net/spotify/country/"

# --- Nguồn 2: ReccoBeats (đặc trưng âm thanh theo Spotify ID, không cần key) ---
RECCOBEATS_BASE = "https://api.reccobeats.com/v1"
RECCOBEATS_BATCH = 40

# --- Nguồn 3: Deezer (ngày phát hành, thể loại, hãng đĩa, explicit, BPM) ---
DEEZER_BASE = "https://api.deezer.com"

# --- Nguồn 4: MusicBrainz (quốc gia / loại nghệ sĩ) ---
MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
MB_MIN_SCORE = 90          # điểm khớp tối thiểu khi tìm nghệ sĩ theo tên

# Nhiều bài ở BXH toàn cầu là nhạc từ 2013-2017; chỉ làm giàu dữ liệu cho N bài
# có tổng lượt stream cao nhất để thời gian thu thập hợp lý (~20 phút).
GLOBAL_ENRICH_LIMIT = 2500

# Tên ứng dụng gửi kèm request (MusicBrainz yêu cầu User-Agent có tên ứng dụng)
USER_AGENT = "BTL-TQHDL-SpotifyVN/1.0 (student data-visualization project)"

# Giới hạn tốc độ gọi API (số giây tối thiểu giữa 2 request tới cùng 1 host)
RATE_LIMIT_SECONDS = {
    "kworb.net": 1.0,
    "api.reccobeats.com": 0.25,
    "api.deezer.com": 0.12,     # Deezer cho phép 50 request / 5 giây
    "musicbrainz.org": 1.1,     # MusicBrainz yêu cầu tối đa 1 request / giây
}

# --- Dashboard ---
REFRESH_HOURS = 6           # Dữ liệu cũ hơn số giờ này thì dashboard tự cập nhật
AUTO_CHECK_MINUTES = 30     # Chu kỳ dashboard kiểm tra độ mới của dữ liệu

# Ngưỡng phân nhóm thành công (theo phân vị số ngày trụ hạng TRONG từng thị trường)
LONG_RUN_QUANTILE = 0.75    # >= Q75 số ngày  -> "Trụ lâu"
SHORT_RUN_QUANTILE = 0.25   # <= Q25 số ngày  -> "Lướt qua"

AUDIO_FEATURES = [
    "danceability", "energy", "valence", "acousticness",
    "speechiness", "instrumentalness", "liveness",
]
NUMERIC_FEATURES = AUDIO_FEATURES + ["tempo", "loudness", "duration_min"]

FEATURE_LABELS = {
    "danceability": "Tính khiêu vũ",
    "energy": "Năng lượng",
    "valence": "Cảm xúc tích cực",
    "acousticness": "Độ mộc (acoustic)",
    "speechiness": "Tỷ lệ lời nói/rap",
    "instrumentalness": "Tỷ lệ không lời",
    "liveness": "Cảm giác live",
    "tempo": "Nhịp (BPM)",
    "loudness": "Âm lượng (dB)",
    "duration_min": "Thời lượng (phút)",
}
