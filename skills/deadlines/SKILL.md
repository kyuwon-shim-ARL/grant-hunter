---
name: deadlines
description: Show upcoming grant deadlines sorted by urgency
---

# Grant Deadlines

Show upcoming grant deadlines with color-coded urgency.

## Execution

1. Call `grant_deadlines` MCP tool
   - Default: next 90 days
   - If user specifies timeframe (e.g., "this month", "next 30 days"), adjust days parameter

2. Format as urgency-coded list:
   - **URGENT** (D-7 이내): 빨간색/bold - 즉시 행동 필요
   - **SOON** (D-14 이내): 주황색 - 준비 시작
   - **UPCOMING** (D-30 이내): 노란색 - 계획 수립
   - **LATER** (D-30+): 일반 텍스트

3. For each deadline show:
   - D-day count
   - Grant name
   - Source/agency
   - Funding amount (if known)
   - Eligibility status

4. If Google Workspace MCP is available, offer to create calendar events for any deadlines not yet in calendar

## Korean Output
When user communicates in Korean, output in Korean:
- "마감 D-7 이내" instead of "Due within 7 days"
- "즉시 준비 필요" instead of "Immediate action needed"
