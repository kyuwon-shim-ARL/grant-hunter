#!/usr/bin/env python3
"""
extract_deadlines.py - Parse grant deadlines from grant_survey_report.md

Outputs JSON list of grants with deadline info.
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

REPORT_PATH = Path(__file__).parent.parent / "grant_survey_report.md"

# URL map from the report
URL_MAP = {
    "Horizon Europe HLTH-2026": "https://hadea.ec.europa.eu",
    "Google.org AI for Science": "https://www.google.org/impact-challenges/ai-science/",
    "SPARK-PN 2026": "https://pasteur-network.org",
    "CARB-X 2026": "https://carb-x.org",
    "RIGHT Foundation": "https://rightfoundation.kr",
    "KHIDI 감염병 예방·치료 기술개발": "https://www.khidi.or.kr",
    "KDCA 항생제내성 R&D": "https://www.kdca.go.kr",
    "Gr-ADI": "https://gcgh.grandchallenges.org/challenge/innovations-gram-negative-antibiotic-discovery",
    "KDDF 국가신약개발사업": "https://www.kddf.org",
    "GFID 범부처 감염병 R&D": "https://www.gfid.or.kr",
    "IITP AI 핵심기술개발": "https://www.iitp.kr",
    "NRF 글로벌연구실": "https://www.msit.go.kr",
    "NIH/NIAID R01/R21": "https://www.niaid.nih.gov/grants-contracts/international-applications",
    "삼성미래기술육성재단": "https://www.samsungstf.org",
    "KHIDI 미해결 치료제 도전 기술개발": "https://www.khidi.or.kr",
    "NRF 바이오·의료기술개발": "https://www.msit.go.kr",
    "Gates Grand Challenges": "https://gcgh.grandchallenges.org",
    "Microsoft AI for Health": "https://www.microsoft.com/en-us/research/project/ai-for-health/",
    "NRF 한-해외 국제협력연구": "https://www.msit.go.kr",
    "IHI AMR Accelerator": "https://hadea.ec.europa.eu",
    "GARDP 파트너십": "https://gardp.org",
    "Novo Nordisk Catalyst Grants": "https://www.novonordisk.com",
    "CZI AI GPU Grant": "https://chanzuckerberg.com/rfa/ai-computing-gpu/",
    "KISTI 슈퍼컴 지원": "https://www.kisti.re.kr",
    "NVIDIA Academic Grant": "https://www.nvidia.com/en-us/industries/higher-education-research/academic-grant-program/",
    "AWS Research Credits": "https://aws.amazon.com/research-credits/",
    "DFG/NRF 한-독 공동": "https://www.msit.go.kr",
    "PHC STAR 한-불": "https://fundit.fr/en/calls/phc-starcooperation-scientifique-franco-coreenne",
    "EU MSCA Postdoctoral": "https://hadea.ec.europa.eu",
    "NRF 신진/중견연구": "https://www.msit.go.kr",
    "대웅재단": "https://www.daewoongfoundation.or.kr",
    "Google Cloud Credits": "https://cloud.google.com/edu/researchers",
}

# Scale map from the report tables
SCALE_MAP = {
    "Horizon Europe HLTH-2026": "€3-10M/컨소시엄",
    "Google.org AI for Science": "$0.5-3M + Cloud",
    "SPARK-PN 2026": "미공개 (수억 추정)",
    "CARB-X 2026": "$1-20M",
    "RIGHT Foundation": "~40억원 ($3M)",
    "KHIDI 감염병 예방·치료 기술개발": "3-20억/년",
    "KDCA 항생제내성 R&D": "2-10억/년",
    "Gr-ADI": "$1-5M",
    "KDDF 국가신약개발사업": "3-20억/년",
    "GFID 범부처 감염병 R&D": "5-30억/년",
    "IITP AI 핵심기술개발": "5-30억/년",
    "NRF 글로벌연구실": "3-5억/년",
    "NIH/NIAID R01/R21": "~$500K/년",
    "삼성미래기술육성재단": "수억-수십억",
    "KHIDI 미해결 치료제 도전 기술개발": "5-15억/년",
    "NRF 바이오·의료기술개발": "5-20억/년",
    "Gates Grand Challenges": "$100K-$1M+",
    "Microsoft AI for Health": "~$900K + Azure",
    "NRF 한-해외 국제협력연구": "1-5억/년",
    "IHI AMR Accelerator": "€5-20M/컨소시엄",
    "GARDP 파트너십": "프로젝트별",
    "Novo Nordisk Catalyst Grants": "~€800K",
    "CZI AI GPU Grant": "GPU 자원",
    "KISTI 슈퍼컴 지원": "HPC 자원",
    "NVIDIA Academic Grant": "H100 GPU",
    "AWS Research Credits": "$100K+$250K",
    "DFG/NRF 한-독 공동": "~$50K",
    "PHC STAR 한-불": "~€17K",
    "EU MSCA Postdoctoral": "~€200K",
    "NRF 신진/중견연구": "0.5-5억",
    "대웅재단": "~5천만",
    "Google Cloud Credits": "크레딧",
}

# Hardcoded deadline data derived from the report
# Format: (program_name, tier, deadline_str, deadline_date, uncertain, note)
GRANT_DATA = [
    # Tier 1
    {
        "program_name": "Horizon Europe HLTH-2026 (AMR)",
        "tier": 1,
        "score": 92,
        "deadline_raw": "2026.04.16",
        "deadline_date": "2026-04-16",
        "uncertain": False,
        "note": "⚠️ 긴급 마감. IPP 파리 컨소시엄 즉시 구성 필요",
        "url": "https://hadea.ec.europa.eu",
        "scale": "€3-10M/컨소시엄",
    },
    {
        "program_name": "Google.org AI for Science",
        "tier": 1,
        "score": 90,
        "deadline_raw": "2026.04.17",
        "deadline_date": "2026-04-17",
        "uncertain": False,
        "note": "⚠️ 긴급 마감. 영문 제안서 작성 필요",
        "url": "https://www.google.org/impact-challenges/ai-science/",
        "scale": "$0.5-3M + Cloud",
    },
    {
        "program_name": "SPARK-PN 2026",
        "tier": 1,
        "score": 89,
        "deadline_raw": "2026.05.20",
        "deadline_date": "2026-05-20",
        "uncertain": False,
        "note": "파스퇴르 네트워크 전용. 내부 공모 신청서 준비",
        "url": "https://pasteur-network.org",
        "scale": "미공개 (수억 추정)",
    },
    {
        "program_name": "CARB-X 2026 EOI",
        "tier": 1,
        "score": 85,
        "deadline_raw": "2026.04.22",
        "deadline_date": "2026-04-22",
        "uncertain": False,
        "note": "⚠️ 긴급 마감 (EOI). IP 현황 정리 후 Expression of Interest 제출",
        "url": "https://carb-x.org",
        "scale": "$1-20M",
    },
    {
        "program_name": "RIGHT Foundation",
        "tier": 1,
        "score": 84,
        "deadline_raw": "활성 (확인필요)",
        "deadline_date": "2026-05-01",  # estimated mid-2026
        "uncertain": True,
        "note": "마감일 확인 필요. rightfoundation.kr 현재 RFP 즉시 확인",
        "url": "https://rightfoundation.kr",
        "scale": "~40억원 ($3M)",
    },
    {
        "program_name": "KHIDI 감염병 예방·치료 기술개발",
        "tier": 1,
        "score": 83,
        "deadline_raw": "2026 상반기",
        "deadline_date": "2026-06-30",  # estimated end of H1
        "uncertain": True,
        "note": "상반기 공고 예정. IRIS 등록 및 연구계획서 초안 준비",
        "url": "https://www.khidi.or.kr",
        "scale": "3-20억/년",
    },
    {
        "program_name": "KDCA 항생제내성 R&D",
        "tier": 1,
        "score": 82,
        "deadline_raw": "2026 공고예정",
        "deadline_date": "2026-08-31",  # estimated Q3 based on roadmap
        "uncertain": True,
        "note": "하반기 공고 예정 (추정). 제3차 AMR 관리대책 연계 기획",
        "url": "https://www.kdca.go.kr",
        "scale": "2-10억/년",
    },
    {
        "program_name": "Gr-ADI (Gates/Wellcome/Novo)",
        "tier": 1,
        "score": 80,
        "deadline_raw": "2차 라운드 모니터링",
        "deadline_date": "2026-12-31",  # estimated Q4
        "uncertain": True,
        "note": "2026 Q4 2차 라운드 모니터링 필요",
        "url": "https://gcgh.grandchallenges.org/challenge/innovations-gram-negative-antibiotic-discovery",
        "scale": "$1-5M",
    },
    # Tier 2
    {
        "program_name": "KDDF 국가신약개발사업",
        "tier": 2,
        "score": 79,
        "deadline_raw": "2026 공고",
        "deadline_date": "2026-10-31",  # estimated Q3-Q4
        "uncertain": True,
        "note": "하반기 공고 예정. AI 신약 2단계 과제 기획",
        "url": "https://www.kddf.org",
        "scale": "3-20억/년",
    },
    {
        "program_name": "GFID 범부처 감염병 R&D",
        "tier": 2,
        "score": 78,
        "deadline_raw": "2026 공고",
        "deadline_date": "2027-03-31",  # estimated Q1 2027 based on roadmap
        "uncertain": True,
        "note": "2027 Q1 예정 (추정). 감염병 R&D 기획",
        "url": "https://www.gfid.or.kr",
        "scale": "5-30억/년",
    },
    {
        "program_name": "IITP AI 핵심기술개발",
        "tier": 2,
        "score": 77,
        "deadline_raw": "연 2-3회",
        "deadline_date": "2026-07-31",  # estimated 2nd round
        "uncertain": True,
        "note": "연 2-3회 공모. AMR 진단/내성예측 AI 모델 기획",
        "url": "https://www.iitp.kr",
        "scale": "5-30억/년",
    },
    {
        "program_name": "NRF 글로벌연구실(GRL)",
        "tier": 2,
        "score": 76,
        "deadline_raw": "연 1회",
        "deadline_date": "2026-10-31",  # estimated annual call Q4
        "uncertain": True,
        "note": "연 1회 공모 (추정)",
        "url": "https://www.msit.go.kr",
        "scale": "3-5억/년",
    },
    {
        "program_name": "NIH/NIAID R01/R21",
        "tier": 2,
        "score": 75,
        "deadline_raw": "6월/10월",
        "deadline_date": "2026-06-05",  # June cycle
        "uncertain": False,
        "note": "6월 사이클 마감 06.05, 10월 사이클 10.05. FOA 탐색 및 Program Officer 컨택",
        "url": "https://www.niaid.nih.gov/grants-contracts/international-applications",
        "scale": "~$500K/년",
    },
    {
        "program_name": "NIH/NIAID R01/R21 (10월 사이클)",
        "tier": 2,
        "score": 75,
        "deadline_raw": "10월",
        "deadline_date": "2026-10-05",
        "uncertain": False,
        "note": "10월 사이클 마감",
        "url": "https://www.niaid.nih.gov/grants-contracts/international-applications",
        "scale": "~$500K/년",
    },
    {
        "program_name": "삼성미래기술육성재단",
        "tier": 2,
        "score": 74,
        "deadline_raw": "2026 하반기",
        "deadline_date": "2026-07-31",  # estimated July
        "uncertain": True,
        "note": "하반기 공모 예정 (추정). IPK 신청 자격 사전 이메일 문의 필요",
        "url": "https://www.samsungstf.org",
        "scale": "수억-수십억",
    },
    {
        "program_name": "KHIDI 미해결 치료제 도전 기술개발",
        "tier": 2,
        "score": 73,
        "deadline_raw": "2026 공고",
        "deadline_date": "2026-06-30",
        "uncertain": True,
        "note": "2026 공고 예정",
        "url": "https://www.khidi.or.kr",
        "scale": "5-15억/년",
    },
    {
        "program_name": "NRF 바이오·의료기술개발",
        "tier": 2,
        "score": 72,
        "deadline_raw": "연 4-5차",
        "deadline_date": "2026-06-30",  # estimated mid-year round
        "uncertain": True,
        "note": "연 4-5차 공모",
        "url": "https://www.msit.go.kr",
        "scale": "5-20억/년",
    },
    {
        "program_name": "Gates Grand Challenges",
        "tier": 2,
        "score": 71,
        "deadline_raw": "상시(Rolling)",
        "deadline_date": None,
        "uncertain": True,
        "note": "상시 접수 (Rolling)",
        "url": "https://gcgh.grandchallenges.org",
        "scale": "$100K-$1M+",
    },
    {
        "program_name": "Microsoft AI for Health",
        "tier": 2,
        "score": 70,
        "deadline_raw": "수시",
        "deadline_date": None,
        "uncertain": True,
        "note": "수시 접수",
        "url": "https://www.microsoft.com/en-us/research/project/ai-for-health/",
        "scale": "~$900K + Azure",
    },
    {
        "program_name": "NRF 한-해외 국제협력연구",
        "tier": 2,
        "score": 69,
        "deadline_raw": "연 1회",
        "deadline_date": "2026-10-31",
        "uncertain": True,
        "note": "연 1회 공모 (추정)",
        "url": "https://www.msit.go.kr",
        "scale": "1-5억/년",
    },
    {
        "program_name": "IHI AMR Accelerator",
        "tier": 2,
        "score": 68,
        "deadline_raw": "수시 콜",
        "deadline_date": None,
        "uncertain": True,
        "note": "수시 콜 공모. 2027 Q1 신규 콜 예정",
        "url": "https://hadea.ec.europa.eu",
        "scale": "€5-20M/컨소시엄",
    },
    {
        "program_name": "GARDP 파트너십",
        "tier": 2,
        "score": 67,
        "deadline_raw": "직접 협의",
        "deadline_date": None,
        "uncertain": True,
        "note": "직접 협의 방식",
        "url": "https://gardp.org",
        "scale": "프로젝트별",
    },
    {
        "program_name": "Novo Nordisk Catalyst Grants",
        "tier": 2,
        "score": 65,
        "deadline_raw": "다음 사이클",
        "deadline_date": "2026-12-31",
        "uncertain": True,
        "note": "다음 사이클 예정",
        "url": "https://www.novonordisk.com",
        "scale": "~€800K",
    },
    # Tier 3
    {
        "program_name": "CZI AI GPU Grant",
        "tier": 3,
        "score": 62,
        "deadline_raw": "확인필요",
        "deadline_date": None,
        "uncertain": True,
        "note": "컴퓨팅 자원 확보용",
        "url": "https://chanzuckerberg.com/rfa/ai-computing-gpu/",
        "scale": "GPU 자원",
    },
    {
        "program_name": "KISTI 슈퍼컴 지원",
        "tier": 3,
        "score": 61,
        "deadline_raw": "2026.06",
        "deadline_date": "2026-06-30",
        "uncertain": True,
        "note": "6호기 2026.06 서비스 개시 예정",
        "url": "https://www.kisti.re.kr",
        "scale": "HPC 자원",
    },
    {
        "program_name": "NVIDIA Academic Grant",
        "tier": 3,
        "score": 60,
        "deadline_raw": "2026.06.30",
        "deadline_date": "2026-06-30",
        "uncertain": False,
        "note": "H100 GPU 지원",
        "url": "https://www.nvidia.com/en-us/industries/higher-education-research/academic-grant-program/",
        "scale": "H100 GPU",
    },
    {
        "program_name": "AWS Research Credits",
        "tier": 3,
        "score": 59,
        "deadline_raw": "상시",
        "deadline_date": None,
        "uncertain": True,
        "note": "상시 접수",
        "url": "https://aws.amazon.com/research-credits/",
        "scale": "$100K+$250K",
    },
    {
        "program_name": "DFG/NRF 한-독 공동",
        "tier": 3,
        "score": 58,
        "deadline_raw": "04.xx (추정)",
        "deadline_date": "2026-04-30",
        "uncertain": True,
        "note": "EU 파트너 시딩용. 마감일 추정",
        "url": "https://www.msit.go.kr",
        "scale": "~$50K",
    },
    {
        "program_name": "PHC STAR 한-불",
        "tier": 3,
        "score": 57,
        "deadline_raw": "확인필요",
        "deadline_date": None,
        "uncertain": True,
        "note": "파스퇴르 연계 발판",
        "url": "https://fundit.fr/en/calls/phc-starcooperation-scientifique-franco-coreenne",
        "scale": "~€17K",
    },
    {
        "program_name": "EU MSCA Postdoctoral",
        "tier": 3,
        "score": 56,
        "deadline_raw": "2026.09",
        "deadline_date": "2026-09-30",
        "uncertain": True,
        "note": "연간 공모 예정 (추정). 인력 유치용",
        "url": "https://hadea.ec.europa.eu",
        "scale": "~€200K",
    },
    {
        "program_name": "NRF 신진/중견연구",
        "tier": 3,
        "score": 55,
        "deadline_raw": "확인필요",
        "deadline_date": None,
        "uncertain": True,
        "note": "개인PI 신청",
        "url": "https://www.msit.go.kr",
        "scale": "0.5-5억",
    },
    {
        "program_name": "대웅재단",
        "tier": 3,
        "score": 52,
        "deadline_raw": "2026.08",
        "deadline_date": "2026-08-31",
        "uncertain": True,
        "note": "자격 문의 필요",
        "url": "https://www.daewoongfoundation.or.kr",
        "scale": "~5천만",
    },
    {
        "program_name": "Google Cloud Credits",
        "tier": 3,
        "score": 51,
        "deadline_raw": "상시",
        "deadline_date": None,
        "uncertain": True,
        "note": "상시 접수",
        "url": "https://cloud.google.com/edu/researchers",
        "scale": "크레딧",
    },
]


def parse_grants():
    """Return processed grant deadline list."""
    today = date.today()
    results = []

    for g in GRANT_DATA:
        entry = dict(g)
        # Compute days_until for grants with a known date
        if entry["deadline_date"]:
            dl = date.fromisoformat(entry["deadline_date"])
            entry["days_until"] = (dl - today).days
            entry["urgent"] = entry["days_until"] <= 30 and not entry["uncertain"]
        else:
            entry["days_until"] = None
            entry["urgent"] = False
        results.append(entry)

    # Sort: known dates first (by days_until asc), then unknown
    results.sort(key=lambda x: (x["days_until"] is None, x["days_until"] or 9999))
    return results


def main():
    grants = parse_grants()

    output = {
        "generated_at": datetime.now().isoformat(),
        "source": str(REPORT_PATH),
        "total": len(grants),
        "grants": grants,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
