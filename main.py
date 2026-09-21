
"""
전국 고령화 지도 (Streamlit + Plotly)
-------------------------------------------------
- 시군구별 65세 이상 인구 비율(고령화율)을 5단계 색으로 나눈 지도
- 데이터 출처: https://github.com/greatsong/modudata
"""

import re

import pandas as pd
import plotly.express as px
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


# -------------------------------------------------
# 1. 인구 데이터 불러오기
# -------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population() -> pd.DataFrame:
    # '코드'는 계산할 숫자가 아니라 이름표이므로 반드시 문자열(str)로 읽는다.
    df = pd.read_csv(POPULATION_URL, compression="gzip", dtype={"코드": str})
    # 혹시 앞자리 0이 잘려 있을 경우를 대비해 10자리로 맞춰준다.
    df["코드"] = df["코드"].str.zfill(10)
    return df


population_df = load_population()

# -------------------------------------------------
# 2. 나이별 인구 열 중에서 '계_' (남녀 합계) 열만 골라내기
# -------------------------------------------------
age_cols = [col for col in population_df.columns if col.startswith("계_")]


def parse_age(col_name: str) -> int:
    """'계_0세' -> 0, '계_100세 이상' -> 100 처럼 열 이름에서 나이를 뽑아낸다."""
    if "이상" in col_name:
        return 100
    match = re.search(r"(\d+)세", col_name)
    return int(match.group(1)) if match else -1


age_65_plus_cols = [col for col in age_cols if parse_age(col) >= 65]

# -------------------------------------------------
# 3. 가장 최신 연도만 선택
# -------------------------------------------------
latest_year = population_df["연도"].max()
year_df = population_df[population_df["연도"] == latest_year].copy()

# -------------------------------------------------
# 4. 읍·면·동 단위 -> 시군구 단위로 집계
#    ('코드' 앞 5자리가 시군구 코드)
# -------------------------------------------------
year_df["시군구코드"] = year_df["코드"].str[:5]

# 한 행(읍면동)의 총인구 = 모든 나이대 '계_' 열의 합
year_df["총인구"] = year_df[age_cols].sum(axis=1)
# 한 행(읍면동)의 65세 이상 인구 = 65세 이상 '계_' 열의 합
year_df["인구65이상"] = year_df[age_65_plus_cols].sum(axis=1)

sigungu_df = (
    year_df.groupby("시군구코드", as_index=False)
    .agg(
        시도=("시도", "first"),
        시군구=("시군구", "first"),
        총인구=("총인구", "sum"),
        인구65이상=("인구65이상", "sum"),
    )
)
sigungu_df["고령화율"] = (sigungu_df["인구65이상"] / sigungu_df["총인구"] * 100).round(2)

# 5단계 구간으로 나누기 (지도 색상 & 범례에 사용)
sigungu_df["구간"] = pd.cut(
    sigungu_df["고령화율"],
    bins=BIN_EDGES,
    labels=BIN_LABELS,
    right=False,  # 19.0%는 '19~23%' 구간에 포함
)

# -------------------------------------------------
# 5. 지도 경계 데이터(GeoJSON) 불러오기
# -------------------------------------------------
@st.cache_data(show_spinner="지도 경계 데이터를 불러오는 중입니다...")
def load_boundary() -> dict:
    response = requests.get(BOUNDARY_URL)
    response.raise_for_status()
    return response.json()


boundary_geojson = load_boundary()

# -------------------------------------------------
# 6. 단계구분도(Choropleth) 그리기
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

st.plotly_chart(fig, use_container_width=True)
st.caption(f"기준 연도: {latest_year}년 | 고령화율 = 65세 이상 인구 ÷ 전체 인구 × 100")

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
