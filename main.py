"""
전국 고령화 지도 (Streamlit + Plotly)
-------------------------------------------------
- 시군구별 65세 이상 인구 비율(고령화율)을 5단계 색으로 나눈 지도
- 지도에서 시군구를 클릭하면 그 지역의 연도별 고령화율 추이와
  최신 연도 인구 피라미드를 함께 보여준다.
- 데이터 출처: https://github.com/greatsong/modudata
"""

import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# -------------------------------------------------
# 0. 페이지 기본 설정
# -------------------------------------------------
st.set_page_config(page_title="전국 고령화 지도", layout="wide")
st.title("전국 시군구 고령화 지도")
st.caption("시군구별 65세 이상 인구 비율(고령화율)을 색으로 표현한 단계구분도입니다.")

POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
)
BOUNDARY_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"
)

# 5단계 색 구간의 경계값 (%)
BIN_EDGES = [0, 19, 23, 28, 38, 100]
BIN_LABELS = ["19% 미만", "19~23%", "23~28%", "28~38%", "38% 이상"]
# 옅은 색 -> 진한 색 순서 (5단계)
BIN_COLORS = ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]

# 인구 피라미드용 5세 단위 연령대 순서 (0-4 ~ 95-99, 100+)
AGE_BIN_ORDER = [f"{i}-{i + 4}세" for i in range(0, 100, 5)] + ["100세 이상"]


def parse_age(col_name: str) -> int:
    """'계_0세' -> 0, '남_100세 이상' -> 100 처럼 열 이름에서 나이를 뽑아낸다."""
    if "이상" in col_name:
        return 100
    match = re.search(r"(\d+)세", col_name)
    return int(match.group(1)) if match else -1


def to_age_bin(age: int) -> str:
    """나이를 5세 단위 구간 문자열로 바꾼다. 예: 23 -> '20-24세'"""
    if age >= 100:
        return "100세 이상"
    start = (age // 5) * 5
    return f"{start}-{start + 4}세"


# -------------------------------------------------
# 1. 인구 데이터 불러오기
# -------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population() -> pd.DataFrame:
    # '코드'는 계산할 숫자가 아니라 이름표이므로 반드시 문자열(str)로 읽는다.
    df = pd.read_csv(POPULATION_URL, compression="gzip", dtype={"코드": str})
    # 혹시 앞자리 0이 잘려 있을 경우를 대비해 10자리로 맞춰준다.
    df["코드"] = df["코드"].str.zfill(10)
    df["시군구코드"] = df["코드"].str[:5]
    return df


population_df = load_population()

# 나이별 인구 열 중에서 '계_'(남녀 합계), '남_', '여_' 열을 각각 골라낸다.
age_cols = [col for col in population_df.columns if col.startswith("계_")]
male_cols = [col for col in population_df.columns if col.startswith("남_")]
female_cols = [col for col in population_df.columns if col.startswith("여_")]
age_65_plus_cols = [col for col in age_cols if parse_age(col) >= 65]

# -------------------------------------------------
# 2. 연도별 · 시군구별 고령화율 (전체 연도 - 추이 그래프용)
# -------------------------------------------------
@st.cache_data(show_spinner="연도별 통계를 계산하는 중입니다...")
def build_trend(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    tmp["총인구"] = tmp[age_cols].sum(axis=1)
    tmp["인구65이상"] = tmp[age_65_plus_cols].sum(axis=1)
    grouped = (
        tmp.groupby(["연도", "시군구코드"], as_index=False)
        .agg(
            시도=("시도", "first"),
            시군구=("시군구", "first"),
            총인구=("총인구", "sum"),
            인구65이상=("인구65이상", "sum"),
        )
    )
    grouped["고령화율"] = (grouped["인구65이상"] / grouped["총인구"] * 100).round(2)
    return grouped


trend_df = build_trend(population_df)

# -------------------------------------------------
# 3. 가장 최신 연도만 선택 -> 지도용 데이터
# -------------------------------------------------
latest_year = population_df["연도"].max()
year_df = population_df[population_df["연도"] == latest_year].copy()

sigungu_df = trend_df[trend_df["연도"] == latest_year].copy()

# 5단계 구간으로 나누기 (지도 색상 & 범례에 사용)
sigungu_df["구간"] = pd.cut(
    sigungu_df["고령화율"],
    bins=BIN_EDGES,
    labels=BIN_LABELS,
    right=False,  # 19.0%는 '19~23%' 구간에 포함
)

# -------------------------------------------------
# 4. 지도 경계 데이터(GeoJSON) 불러오기
# -------------------------------------------------
@st.cache_data(show_spinner="지도 경계 데이터를 불러오는 중입니다...")
def load_boundary() -> dict:
    response = requests.get(BOUNDARY_URL)
    response.raise_for_status()
    return response.json()


boundary_geojson = load_boundary()

# -------------------------------------------------
# 5. 단계구분도(Choropleth) 그리기
# -------------------------------------------------
fig = px.choropleth(
    sigungu_df,
    geojson=boundary_geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="구간",
    category_orders={"구간": BIN_LABELS},
    color_discrete_sequence=BIN_COLORS,
    hover_name="시군구",
    hover_data={
        "시도": True,
        "고령화율": ":.2f",
        "시군구코드": False,
        "구간": False,
    },
    custom_data=["시군구코드", "시군구", "시도"],
    labels={"고령화율": "고령화율(%)", "시도": "시도", "구간": "구간"},
)

# 배경 지도 타일(바다, 육지, 국경선 등) 없이 경계선만 보이도록 설정
fig.update_geos(
    visible=False,
    fitbounds="locations",
)
fig.update_layout(
    margin={"r": 0, "t": 30, "l": 0, "b": 0},
    height=700,
    legend_title_text=f"{latest_year}년 고령화율 구간",
)
fig.update_traces(marker_line_color="white", marker_line_width=0.5)

st.caption("지도의 시군구를 클릭하면 아래에 해당 지역의 상세 그래프가 나타납니다.")

map_event = st.plotly_chart(
    fig,
    use_container_width=True,
    on_select="rerun",
    selection_mode="points",
    key="choropleth_map",
)
st.caption(f"기준 연도: {latest_year}년 | 고령화율 = 65세 이상 인구 ÷ 전체 인구 × 100")

# -------------------------------------------------
# 6. 선택한 시군구의 상세 그래프 (연도별 추이 + 인구 피라미드)
# -------------------------------------------------
selected_points = map_event.get("selection", {}).get("points", []) if map_event else []

if not selected_points:
    st.info("지도에서 시군구 하나를 클릭하면 연도별 고령화율 추이와 인구 피라미드를 볼 수 있습니다.")
else:
    # 여러 지역을 선택해도 첫 번째로 클릭한 지역만 보여준다.
    point = selected_points[0]
    selected_code, selected_sigungu, selected_sido = point["customdata"]

    st.subheader(f"{selected_sido} {selected_sigungu} 상세 보기")

    detail_col1, detail_col2 = st.columns(2)

    # --- 6-1. 연도별 고령화율 추이 (선 그래프) ---
    with detail_col1:
        region_trend = trend_df[trend_df["시군구코드"] == selected_code].sort_values("연도")
        trend_fig = px.line(
            region_trend,
            x="연도",
            y="고령화율",
            markers=True,
            labels={"연도": "연도", "고령화율": "고령화율(%)"},
            title=f"{selected_sigungu} 연도별 고령화율 추이",
        )
        trend_fig.update_layout(height=420)
        st.plotly_chart(trend_fig, use_container_width=True)

    # --- 6-2. 최신 연도 인구 피라미드 (5세 단위) ---
    with detail_col2:
        region_rows = year_df[year_df["시군구코드"] == selected_code]

        records = []
        for col in male_cols:
            records.append(
                {"연령대": to_age_bin(parse_age(col)), "성별": "남성", "인구": region_rows[col].sum()}
            )
        for col in female_cols:
            records.append(
                {"연령대": to_age_bin(parse_age(col)), "성별": "여성", "인구": region_rows[col].sum()}
            )
        pyramid_df = pd.DataFrame(records)
        pyramid_df = pyramid_df.groupby(["연령대", "성별"], as_index=False)["인구"].sum()

        # 남성은 왼쪽(음수), 여성은 오른쪽(양수)으로 그려서 피라미드 모양을 만든다.
        pyramid_df["표시값"] = pyramid_df.apply(
            lambda row: -row["인구"] if row["성별"] == "남성" else row["인구"], axis=1
        )

        pyramid_fig = go.Figure()
        for gender, color in [("남성", "#4C72B0"), ("여성", "#DD8452")]:
            gender_df = pyramid_df[pyramid_df["성별"] == gender].set_index("연령대").reindex(AGE_BIN_ORDER).reset_index()
            pyramid_fig.add_trace(
                go.Bar(
                    y=gender_df["연령대"],
                    x=gender_df["표시값"],
                    name=gender,
                    orientation="h",
                    marker_color=color,
                    customdata=gender_df["인구"],
                    hovertemplate="%{y} " + gender + ": %{customdata:,.0f}명<extra></extra>",
                )
            )

        max_abs = int(pyramid_df["인구"].max() * 1.1) if not pyramid_df.empty else 1
        pyramid_fig.update_layout(
            title=f"{selected_sigungu} {latest_year}년 인구 피라미드",
            barmode="relative",
            height=420,
            xaxis=dict(
                title="인구수(명)",
                range=[-max_abs, max_abs],
                tickvals=[-max_abs, -max_abs // 2, 0, max_abs // 2, max_abs],
                ticktext=[f"{max_abs:,}", f"{max_abs // 2:,}", "0", f"{max_abs // 2:,}", f"{max_abs:,}"],
            ),
            yaxis=dict(title="연령대", categoryorder="array", categoryarray=AGE_BIN_ORDER),
        )
        st.plotly_chart(pyramid_fig, use_container_width=True)

# -------------------------------------------------
# 7. 고령화율 상위 10곳 / 하위 10곳 표
# -------------------------------------------------
st.subheader("고령화율 상위·하위 10개 시군구")

table_df = sigungu_df[["시도", "시군구", "고령화율"]].copy()
table_df = table_df.rename(columns={"고령화율": "고령화율(%)"})

top10 = table_df.sort_values("고령화율(%)", ascending=False).head(10).reset_index(drop=True)
bottom10 = table_df.sort_values("고령화율(%)", ascending=True).head(10).reset_index(drop=True)

top10.index = top10.index + 1
bottom10.index = bottom10.index + 1

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**고령화율 높은 지역 TOP 10**")
    st.dataframe(top10, use_container_width=True)

with col_right:
    st.markdown("**고령화율 낮은 지역 TOP 10**")
    st.dataframe(bottom10, use_container_width=True)
