import streamlit as st

# 페이지 기본 설정
st.set_page_config(
    page_title="에어컨 예상 전기요금 계산기",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 스타일 커스터마이징
st.markdown("""
<style>
    .metric-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    .metric-title {
        font-size: 0.9rem;
        color: #64748b;
        margin-bottom: 6px;
        font-weight: 600;
    }
    .metric-value {
        font-size: 1.9rem;
        font-weight: 800;
        color: #0f172a;
    }
    .metric-sub {
        font-size: 0.85rem;
        color: #475569;
        margin-top: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 1. 기초 통계 데이터 (2023년 가구에너지패널조사 및 한전 하계 요금표 기준)
# ---------------------------------------------------------
AC_SPECS = {
    "분리 벽걸이형": {"watt": 780, "avg_hours": 3.1},
    "분리 스탠드형": {"watt": 1650, "avg_hours": 3.4},
    "멀티형 (스탠드+벽걸이)": {"watt": 2150, "avg_hours": 3.8},
    "시스템 에어컨 (천장형)": {"watt": 2400, "avg_hours": 3.6},
}

DRIVE_TYPE_FACTOR = {
    "인버터형 (신형 · 2011년 이후 대부분)": 0.58,  # 희망온도 도달 후 저전력 유지
    "정속형 (구형 · 실외기 계속 가동)": 0.92,
}

WIND_FACTOR = {
    "약풍 / 자동": 0.90,
    "중풍": 1.00,
    "강풍 / 파워냉방": 1.15,
}

# 가구원 수 및 평형에 따른 비냉방기(평소) 월 기본 전력사용량(kWh)
BASE_USAGE_BY_MEMBERS = {
    "1인 가구": 195,
    "2인 가구": 255,
    "3인 가구": 310,
    "4인 이상 가구": 365,
}

AREA_ADJUSTMENT = {
    "10평대 이하 (40㎡ 미만)": 0.85,
    "20평대 (40~65㎡)": 0.95,
    "30평대 (66~99㎡)": 1.05,
    "40평대 이상 (100㎡ 이상)": 1.20,
}

# ---------------------------------------------------------
# 2. 한전 주택용(저압) 하계(7~8월) 전기요금 계산 함수
# ---------------------------------------------------------
def calc_kepco_summer_bill(kwh: float) -> int:
    if kwh <= 0:
        return 0
    # 하계 누진 구간: 1단계(~300), 2단계(301~450), 3단계(451~)
    if kwh <= 300:
        base_fee = 910
        energy_fee = kwh * 120.0
    elif kwh <= 450:
        base_fee = 1600
        energy_fee = (300 * 120.0) + ((kwh - 300) * 214.6)
    else:
        base_fee = 7300
        energy_fee = (300 * 120.0) + (150 * 214.6) + ((kwh - 450) * 307.3)

    # 기후환경요금(9원/kWh) + 연료비조정요금(5원/kWh)
    extra_fee = kwh * (9.0 + 5.0)
    subtotal = base_fee + energy_fee + extra_fee

    # 부가가치세(10%) + 전력산업기반기금(3.7%, 10원 미만 절사)
    vat = round(subtotal * 0.1)
    fund = int((subtotal * 0.037) // 10 * 10)
    total = int((subtotal + vat + fund) // 10 * 10)
    return total

def calc_ac_kwh(ac_type, drive_type, units, days, hours, temp, wind, area_label):
    base_watt = AC_SPECS[ac_type]["watt"]
    drive_ratio = DRIVE_TYPE_FACTOR[drive_type]
    wind_ratio = WIND_FACTOR[wind]
    area_ratio = AREA_ADJUSTMENT[area_label]

    # 설정온도 24도 기준 1도 낮출 때마다 약 7% 소비전력 증가, 높일 때마다 약 7% 감소
    temp_ratio = max(0.55, 1.0 + (24 - temp) * 0.07)

    effective_kw = (base_watt / 1000.0) * drive_ratio * wind_ratio * temp_ratio * (area_ratio ** 0.5)
    total_kwh = effective_kw * units * days * hours
    return round(total_kwh, 1)

# ---------------------------------------------------------
# 3. 사이드바: 사용자 입력 영역
# ---------------------------------------------------------
with st.sidebar:
    st.header("🏠 가구 및 거주 환경")
    members = st.selectbox("가구원 수", list(BASE_USAGE_BY_MEMBERS.keys()), index=2)
    area = st.selectbox("주택 평형", list(AREA_ADJUSTMENT.keys()), index=2)

    st.divider()
    st.header("❄️ 에어컨 기기 정보")
    ac_type = st.selectbox("에어컨 종류", list(AC_SPECS.keys()), index=1)
    drive_type = st.radio("냉방 방식", list(DRIVE_TYPE_FACTOR.keys()), index=0)
    units = st.number_input("가동 대수 (대)", min_value=1, max_value=5, value=1, step=1)

    st.divider()
    st.header("⏱️ 나의 월간 사용 패턴")
    days = st.slider("월 사용 일수 (일)", min_value=1, max_value=31, value=25)
    hours = st.slider("일평균 가동 시간 (시간)", min_value=0.5, max_value=24.0, value=5.0, step=0.5)
    temp = st.slider("희망 설정 온도 (℃)", min_value=18, max_value=28, value=24)
    wind = st.select_slider("바람 세기", options=list(WIND_FACTOR.keys()), value="중풍")

# ---------------------------------------------------------
# 4. 요금 계산 (사용자 예상치 vs 동일 조건 가구 평균)
# ---------------------------------------------------------
# 1) 평소 기본 사용량 및 기본 요금
base_kwh = round(BASE_USAGE_BY_MEMBERS