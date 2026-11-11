"""Các hàm vẽ biểu đồ Plotly (dùng chung cho dashboard và xuất hình cho báo cáo)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import config
from src import analysis

# Bảng màu đã kiểm tra an toàn cho người mù màu (thứ tự cố định, không xoay vòng)
MARKET_COLORS = {"vn": "#eb6834", "global": "#2a78d6"}
MARKET_NAMES = config.MARKETS
REGION_COLORS = {"Việt Nam": "#eb6834", "Âu - Mỹ": "#2a78d6", "Hàn Quốc": "#1baf7a",
                 "Nhật Bản": "#eda100", "Hoa ngữ": "#e87ba4", "Latin": "#008300",
                 "Đông Nam Á khác": "#6250d6", "Khác": "#9a988f", "Chưa xác định": "#c9c7bf"}
TIER_COLORS = {"Trụ lâu": "#1baf7a", "Trung bình": "#b8b6ad", "Lướt qua": "#e87ba4",
               "Đang trên BXH": "#eda100"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e4dc"
SEQ = ["#f1f6fd", "#c6dbf5", "#8db7ea", "#4f8fdc", "#2a78d6", "#1d5aa6", "#123c70"]


def style(fig: go.Figure, height: int = 380, legend: bool = True) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=10, r=10, t=84 if legend else 48, b=10),
        font=dict(family="Inter, Segoe UI, Arial", size=13, color=INK),
        showlegend=legend, hoverlabel=dict(font_size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, title_text=""),
        bargap=0.25,
    )
    if fig.layout.title.text:  # chỉ định dạng tiêu đề khi có tiêu đề (tránh hiện chữ "undefined")
        fig.update_layout(title=dict(font=dict(size=15), y=0.98, yanchor="top", x=0.01, xanchor="left"))
    else:
        fig.update_layout(margin=dict(t=56 if legend else 16))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=INK2))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=INK2))
    return fig


def _empty(msg="Không đủ dữ liệu cho bộ lọc hiện tại"):
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=14, color=INK2))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, 260, legend=False)


# ----------------------------------------------------------------------------
def region_share_bar(d: pd.DataFrame, weight: str | None = None, title: str = "") -> go.Figure:
    s = analysis.share_table(d, "region", "market", weight)
    if s.empty:
        return _empty()
    s["Thị trường"] = s["market"].map(MARKET_NAMES)
    order = [r for r in REGION_COLORS if r in set(s["region"])]
    fig = px.bar(s, y="Thị trường", x="share", color="region", orientation="h",
                 category_orders={"region": order}, color_discrete_map=REGION_COLORS,
                 custom_data=["region", "value"], title=title or None)
    fig.update_traces(marker_line_color="white", marker_line_width=2,
                      hovertemplate="%{customdata[0]}: %{x:.1%}<br>(%{customdata[1]:,.0f})<extra></extra>",
                      texttemplate="%{x:.0%}", textposition="inside", insidetextanchor="middle")
    fig.update_layout(barmode="stack", uniformtext_minsize=10, uniformtext_mode="hide")
    fig.update_xaxes(tickformat=".0%", range=[0, 1], title="")
    fig.update_yaxes(title="")
    return style(fig, 260)


def longevity_ecdf(d: pd.DataFrame) -> go.Figure:
    if d.empty:
        return _empty()
    fig = go.Figure()
    for m in [m for m in MARKET_COLORS if m in set(d["market"])]:
        x = np.sort(d.loc[d["market"] == m, "days"].astype(float).values)
        y = 1 - np.arange(1, len(x) + 1) / len(x)
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=MARKET_NAMES[m],
                                 line=dict(color=MARKET_COLORS[m], width=2),
                                 hovertemplate="%{y:.0%} số bài trụ ≥ %{x:.0f} ngày<extra>" + MARKET_NAMES[m] + "</extra>"))
    fig.update_xaxes(type="log", title="Số ngày có mặt trên BXH Top 200 (thang log)")
    fig.update_yaxes(tickformat=".0%", title="Tỷ lệ bài trụ được ít nhất X ngày")
    fig.update_layout(title="Bài hát trụ hạng bao lâu?")
    return style(fig, 360)


def feature_effect_dots(eff: pd.DataFrame, label_a: str, label_b: str, title: str) -> go.Figure:
    if eff.empty:
        return _empty()
    e = eff.copy()
    e["color"] = np.where(~e["significant"], "#b8b6ad", np.where(e["d"] > 0, "#1baf7a", "#e87ba4"))
    fig = go.Figure()
    fig.add_vline(x=0, line_color=INK2, line_width=1)
    fig.add_trace(go.Scatter(
        x=e["d"], y=e["label"], mode="markers",
        marker=dict(size=11, color=e["color"], line=dict(color="white", width=2)),
        error_x=dict(type="data", symmetric=False, array=e["hi"] - e["d"], arrayminus=e["d"] - e["lo"],
                     color="#9a988f", thickness=1.5, width=0),
        customdata=np.stack([e["mean_a"], e["mean_b"], e["n_a"], e["n_b"]], axis=1),
        hovertemplate=(f"<b>%{{y}}</b><br>Chênh lệch chuẩn hóa: %{{x:.2f}}<br>"
                       f"TB {label_a}: %{{customdata[0]:.2f}} (n=%{{customdata[2]}})<br>"
                       f"TB {label_b}: %{{customdata[1]:.2f}} (n=%{{customdata[3]}})<extra></extra>"),
        showlegend=False))
    fig.update_xaxes(title=f"← cao hơn ở {label_b}     Cohen's d     cao hơn ở {label_a} →")
    fig.update_yaxes(title="")
    fig.update_layout(title=title)
    return style(fig, 40 * len(e) + 120, legend=False)


def feature_box(d: pd.DataFrame, feature: str, by: str = "market") -> go.Figure:
    x = d[d[feature].notna()].copy()
    if x.empty:
        return _empty()
    if by == "market":
        x["Nhóm"] = x["market"].map(MARKET_NAMES)
        cmap = {MARKET_NAMES[k]: v for k, v in MARKET_COLORS.items()}
    else:
        x["Nhóm"] = x[by]
        cmap = TIER_COLORS
    fig = px.box(x, x="Nhóm", y=feature, color="Nhóm", color_discrete_map=cmap, points=False,
                 hover_data={"title": True, "artist_main": True, "Nhóm": False})
    fig.update_yaxes(title=config.FEATURE_LABELS.get(feature, feature))
    fig.update_xaxes(title="")
    return style(fig, 340, legend=False)


def grouped_share(d: pd.DataFrame, col: str, title: str, order=None, top: int | None = None) -> go.Figure:
    s = analysis.share_table(d, col, "market")
    if s.empty:
        return _empty()
    if top:
        keep = s.groupby(col)["value"].sum().nlargest(top).index
        s = s[s[col].isin(keep)]
    s["Thị trường"] = s["market"].map(MARKET_NAMES)
    order = order or s.groupby(col)["share"].max().sort_values(ascending=False).index.tolist()
    fig = px.bar(s, x=col, y="share", color="Thị trường", barmode="group",
                 category_orders={col: [o for o in order if o in set(s[col])],
                                  "Thị trường": [MARKET_NAMES[m] for m in MARKET_COLORS]},
                 color_discrete_map={MARKET_NAMES[k]: v for k, v in MARKET_COLORS.items()},
                 custom_data=["value"], title=title)
    fig.update_traces(marker_line_color="white", marker_line_width=2,
                      hovertemplate="%{x}<br>%{y:.1%} (%{customdata[0]:,.0f} bài)<extra>%{fullData.name}</extra>")
    fig.update_yaxes(tickformat=".0%", title="Tỷ trọng số bài")
    fig.update_xaxes(title="")
    return style(fig, 360)


def success_rate_bar(t: pd.DataFrame, title: str) -> go.Figure:
    if t.empty:
        return _empty("Không có nhóm nào đủ số bài tối thiểu")
    base = t["base_rate"].iloc[0]
    ticks = [f"{c}<br><span style='font-size:11px;color:{INK2}'>n={int(n)}</span>" for c, n in zip(t["category"], t["n"])]
    fig = go.Figure(go.Bar(
        x=t["category"], y=t["rate"], marker_color=np.where(t["lift"] >= 1, "#1baf7a", "#b8b6ad"),
        marker_line_color="white", marker_line_width=2,
        error_y=dict(type="data", symmetric=False, array=t["hi"] - t["rate"], arrayminus=t["rate"] - t["lo"],
                     color="#7d7b73", thickness=1.2, width=4),
        customdata=np.stack([t["n"], t["n_long"], t["lift"]], axis=1),
        hovertemplate="<b>%{x}</b><br>Tỷ lệ trụ lâu: %{y:.1%}<br>%{customdata[1]:.0f}/%{customdata[0]:.0f} bài"
                      "<br>Gấp %{customdata[2]:.2f} lần mức chung<extra></extra>"))
    fig.add_hline(y=base, line_dash="dash", line_color=INK2, line_width=1.5)
    fig.update_yaxes(tickformat=".0%", title="Tỷ lệ bài 'Trụ lâu'", rangemode="tozero")
    fig.update_xaxes(title="", tickmode="array", tickvals=list(t["category"]), ticktext=ticks)
    fig.update_layout(title=f"{title}  ·  đường đứt nét = mức chung {base:.0%}", clickmode="event+select")
    return style(fig, 380, legend=False)


def rate_heatmap(g: pd.DataFrame, title: str) -> go.Figure:
    if g.empty or g["mean"].notna().sum() == 0:
        return _empty()
    z = g.pivot(index="yb", columns="xb", values="mean")
    n = g.pivot(index="yb", columns="xb", values="count")
    xs, ys = [str(c) for c in z.columns], [str(r) for r in z.index]
    zmax = max(0.5, float(np.nanmax(z.values)))
    fig = go.Figure(go.Heatmap(
        z=z.values, x=xs, y=ys, colorscale=[[i / (len(SEQ) - 1), c] for i, c in enumerate(SEQ)],
        zmin=0, zmax=zmax, xgap=2, ygap=2, customdata=n.values,
        colorbar=dict(title=dict(text="Tỷ lệ<br>trụ lâu"), tickformat=".0%"),
        hovertemplate="Năng lượng %{x}<br>Cảm xúc tích cực %{y}<br>Tỷ lệ trụ lâu: %{z:.0%}<br>n=%{customdata} bài<extra></extra>"))
    for i, yv in enumerate(ys):
        for j, xv in enumerate(xs):
            v = z.iloc[i, j]
            if pd.isna(v):
                continue
            dark = v / zmax > 0.55
            fig.add_annotation(x=xv, y=yv, showarrow=False,
                               text=f"<b>{v:.0%}</b><br><span style='font-size:10px'>n={int(n.iloc[i, j])}</span>",
                               font=dict(size=12, color="white" if dark else INK))
    fig.update_xaxes(title="Năng lượng (energy) →")
    fig.update_yaxes(title="Cảm xúc tích cực (valence) →")
    fig.update_layout(title=title + "  ·  ô trống = dưới số bài tối thiểu")
    return style(fig, 420, legend=False)


def rank_history(h: pd.DataFrame) -> go.Figure:
    if h.empty:
        return _empty("Chọn ít nhất một bài để xem lịch sử thứ hạng")
    fig = px.line(h, x="chart_date", y="pos", color="label", markers=True,
                  color_discrete_sequence=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"])
    fig.update_traces(line_width=2, marker_size=8,
                      hovertemplate="%{x|%d/%m/%Y}: hạng %{y}<extra>%{fullData.name}</extra>")
    fig.update_yaxes(autorange="reversed", title="Thứ hạng", rangemode="tozero")
    fig.update_xaxes(title="", tickformat="%d/%m", dtick=86400000)
    fig.update_layout(title="Lịch sử thứ hạng (từ các lần pipeline thu thập)")
    return style(fig, 360)


def fit_percentiles(pct: dict, song: dict, profile: pd.Series) -> go.Figure:
    feats = list(pct)
    labels = [config.FEATURE_LABELS.get(f, f) for f in feats]
    vals = [pct[f] for f in feats]
    colors = ["#1baf7a" if 0.25 <= v <= 0.75 else "#e87ba4" for v in vals]
    fig = go.Figure(go.Bar(
        y=labels, x=vals, orientation="h", marker_color=colors, marker_line_color="white", marker_line_width=2,
        customdata=np.stack([[song[f] for f in feats], [profile[f] for f in feats]], axis=1),
        hovertemplate="%{y}<br>Bài này: %{customdata[0]:.2f}<br>Trung vị nhóm trụ lâu: %{customdata[1]:.2f}"
                      "<br>Cao hơn %{x:.0%} bài trụ lâu<extra></extra>"))
    fig.add_vrect(x0=0.25, x1=0.75, fillcolor="#1baf7a", opacity=0.08, line_width=0)
    fig.add_vline(x=0.5, line_dash="dot", line_color=INK2)
    fig.update_xaxes(range=[0, 1], tickformat=".0%", title="Vị trí so với các bài 'Trụ lâu' (50% = đúng trung vị)")
    fig.update_yaxes(title="")
    fig.update_layout(title="Bài này nằm ở đâu so với nhóm trụ lâu?")
    return style(fig, 340, legend=False)
