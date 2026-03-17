"""Generate MECE taxonomy visualizations using system Python (has matplotlib)."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import json
import re
import collections
import statistics
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, "/home/kyuwon/projects/grant_hunter/src")
from grant_hunter.models import Grant
from grant_hunter.filters import filter_grants, AMR_KEYWORDS, AI_KEYWORDS, DRUG_KEYWORDS
from grant_hunter.eligibility import EligibilityEngine
from grant_hunter.scoring import RelevanceScorer, score_grant_normalized

today = date(2026, 3, 17)
FIG_DIR = Path("/home/kyuwon/projects/grant_hunter/.omc/scientist/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Load data ──────────────────────────────────────────────────────────
print("Loading snapshots...")
snapshots_dir = Path.home() / ".grant-hunter" / "snapshots"
all_grants_raw = []
for snap_file in sorted(snapshots_dir.glob("*.json")):
    with open(snap_file) as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("grants", [])
    all_grants_raw.extend(items)

grants = []
for raw in all_grants_raw:
    r = {k: v for k, v in raw.items() if k != "_source_file"}
    try:
        grants.append(Grant.from_dict(r))
    except Exception:
        pass

filtered = filter_grants(grants)
print(f"Filtered: {len(filtered)}")

engine = EligibilityEngine()
scorer = RelevanceScorer()

kw_file = Path("/home/kyuwon/projects/grant_hunter/src/grant_hunter/data/keywords.json")
with open(kw_file) as f:
    kw_data = json.load(f)

amr_kw = [w for l in kw_data["amr"].values() for w in l]
ai_kw  = [w for l in kw_data["ai"].values()  for w in l]
drug_kw = [w for l in kw_data["drug_discovery"].values() for w in l]

def count_kw_hits(text, kw_list):
    text_l = text.lower()
    return [kw for kw in kw_list if re.search(r'\b' + re.escape(kw.lower()) + r'\b', text_l)]

stage_keywords = {
    "basic":         ["mechanism", "pathway", "structure", "genomics", "molecular", "in vitro", "in vivo"],
    "translational": ["lead compound", "preclinical", "pharmacokinetics", "ADME", "toxicity", "efficacy"],
    "clinical":      ["clinical trial", "phase I", "phase II", "patient", "randomized", "hospital", "ICU"],
    "implementation":["surveillance", "stewardship", "policy", "guideline", "global health", "one health"],
    "ai_tool":       ["machine learning", "deep learning", "neural network", "AI", "algorithm", "generative"],
}

def extract_nih_activity(grant_id):
    s = re.sub(r'^\d+', '', grant_id)
    m = re.match(r'([A-Z]\d{2}[A-Z]?)', s)
    return m.group(1) if m else "OTHER"

def classify_funding_type(g):
    mech = g._mechanism
    prefix = mech[0] if mech and mech != "OTHER" else "?"
    activity = mech[:3]
    if prefix == "R":
        return "industry_partnership" if activity in ("R41", "R42", "R43", "R44") else "research_grant"
    elif prefix in ("K", "F"):
        return "individual_award"
    elif prefix == "U":
        return "cooperative_agreement"
    elif prefix in ("P", "S"):
        return "center_infrastructure"
    elif prefix == "T":
        return "training_program"
    return "other"

def classify_domain(g):
    amr_cnt = len(g._amr_hits)
    ai_cnt  = len(g._ai_hits)
    drug_cnt = len(g._drug_hits)
    stage = g._stage
    if amr_cnt >= 2 and ai_cnt >= 2:
        return "amr_ai_core"
    if amr_cnt >= 2 and drug_cnt >= 1:
        return "amr_drug_discovery"
    if ai_cnt >= 3 and amr_cnt >= 1:
        return "ai_computational"
    if amr_cnt >= 2:
        return "amr_core"
    if stage in ("clinical", "translational"):
        return "clinical_translational"
    if stage == "implementation":
        return "implementation_policy"
    return "adjacent"

def classify_tier(g):
    elig = g._eligibility
    score = g._norm_score
    domain = g._domain
    ftype = g._funding_type
    if elig == "ineligible":
        return 4
    if ftype == "individual_award" and elig != "eligible":
        return 4
    core_domains = {"amr_ai_core", "amr_drug_discovery", "ai_computational"}
    if elig == "eligible" and score >= 0.15 and domain in core_domains:
        return 1
    if elig in ("eligible", "uncertain") and score >= 0.12 and domain in core_domains | {"amr_core"}:
        return 2
    if elig in ("eligible", "uncertain") and score >= 0.08:
        return 3
    return 4

# Annotate all grants
for g in filtered:
    result = engine.check(g)
    g._eligibility = result.status
    g._norm_score = score_grant_normalized(g)
    searchable = f"{g.title} {g.description} {' '.join(g.keywords)}"
    g._amr_hits = count_kw_hits(searchable, amr_kw)
    g._ai_hits  = count_kw_hits(searchable, ai_kw)
    g._drug_hits = count_kw_hits(searchable, drug_kw)
    title_desc = f"{g.title} {g.description[:200]}".lower()
    stage_scores = {s: sum(1 for kw in kws if kw.lower() in title_desc) for s, kws in stage_keywords.items()}
    g._stage = max(stage_scores, key=stage_scores.get) if max(stage_scores.values()) > 0 else "basic"
    g._mechanism = extract_nih_activity(g.id)
    g._funding_type = classify_funding_type(g)
    g._domain = classify_domain(g)
    g._tier = classify_tier(g)

print("Annotation done. Generating figures...")

TIER_COLORS = {1: "#1a7340", 2: "#2471a3", 3: "#d68910", 4: "#717d7e"}
DOM_ORDER  = ["amr_ai_core", "amr_drug_discovery", "ai_computational", "amr_core",
              "clinical_translational", "implementation_policy", "adjacent"]
DOM_SHORT  = {
    "amr_ai_core": "AMR+AI Core",
    "amr_drug_discovery": "AMR Drug Disc.",
    "ai_computational": "AI/Comp Tools",
    "amr_core": "AMR Core",
    "clinical_translational": "Clinical/Trans.",
    "implementation_policy": "Impl. & Policy",
    "adjacent": "Adjacent/Broad",
}
DOM_COLORS = ["#1a7340","#27ae60","#2471a3","#5dade2","#d68910","#e74c3c","#95a5a6"]
FT_ORDER  = ["research_grant","cooperative_agreement","industry_partnership",
             "individual_award","center_infrastructure","other"]
FT_SHORT  = {
    "research_grant": "Research\nGrant (R)",
    "cooperative_agreement": "Cooperative\nAgreement (U)",
    "industry_partnership": "SBIR/STTR\n(R41-44)",
    "individual_award": "Individual\nAward (K/F)",
    "center_infrastructure": "Center/\nInfra (P/S)",
    "other": "Other",
}
FT_COLORS = ["#2471a3","#1a7340","#d35400","#8e44ad","#c0392b","#717d7e"]

n = len(filtered)
tier_counts = collections.Counter(g._tier for g in filtered)
dom_counts  = collections.Counter(g._domain for g in filtered)
ft_counts   = collections.Counter(g._funding_type for g in filtered)

# ── Fig 1: Three-panel overview ────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle("Grant Hunter MECE Taxonomy — 898 Filtered NIH Grants (IPK AMR+AI Focus)",
             fontsize=13, fontweight="bold")

# Panel A: Funding type
vals_ft = [ft_counts.get(k, 0) for k in FT_ORDER]
wedges, texts, autotexts = axes[0].pie(
    vals_ft, labels=[FT_SHORT[k] for k in FT_ORDER],
    colors=FT_COLORS,
    autopct=lambda p: f"{p:.0f}%" if p > 4 else "",
    startangle=90, pctdistance=0.72, textprops={"fontsize": 8},
)
axes[0].set_title("A. Primary Axis: Funding Type", fontweight="bold", pad=12)

# Panel B: Research domain
vals_dom = [dom_counts.get(k, 0) for k in DOM_ORDER]
axes[1].pie(vals_dom, labels=[DOM_SHORT[k] for k in DOM_ORDER],
            colors=DOM_COLORS,
            autopct=lambda p: f"{p:.0f}%" if p > 4 else "",
            startangle=90, pctdistance=0.75, textprops={"fontsize": 8})
axes[1].set_title("B. Secondary Axis: Research Domain", fontweight="bold", pad=12)

# Panel C: Priority tiers
tier_labels_p = [
    f"T1 Must Apply\n{tier_counts[1]} ({100*tier_counts[1]/n:.0f}%)",
    f"T2 Prepare\n{tier_counts[2]} ({100*tier_counts[2]/n:.0f}%)",
    f"T3 Monitor\n{tier_counts[3]} ({100*tier_counts[3]/n:.0f}%)",
    f"T4 Archive\n{tier_counts[4]} ({100*tier_counts[4]/n:.0f}%)",
]
axes[2].pie([tier_counts[t] for t in [1,2,3,4]],
            labels=tier_labels_p,
            colors=[TIER_COLORS[t] for t in [1,2,3,4]],
            startangle=90, textprops={"fontsize": 8.5})
axes[2].set_title("C. Priority Tiers (Tertiary)", fontweight="bold", pad=12)

plt.tight_layout()
fig.savefig(FIG_DIR / "fig1_taxonomy_overview.png", dpi=150, bbox_inches="tight")
plt.close()
print("fig1 done")

# ── Fig 2: Tier × Domain heatmap ──────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 4.5))
matrix = np.zeros((4, len(DOM_ORDER)), dtype=int)
for g in filtered:
    t = g._tier - 1
    d = DOM_ORDER.index(g._domain) if g._domain in DOM_ORDER else len(DOM_ORDER)-1
    matrix[t, d] += 1

im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto", vmin=0)
ax.set_xticks(range(len(DOM_ORDER)))
ax.set_xticklabels([DOM_SHORT[k] for k in DOM_ORDER], rotation=25, ha="right", fontsize=9)
ax.set_yticks(range(4))
ax.set_yticklabels(["T1 Must Apply","T2 Prepare","T3 Monitor","T4 Archive"], fontsize=9)
ax.set_title("Grant Count: Priority Tier × Research Domain (n=898)", fontsize=11, fontweight="bold")
for i in range(4):
    for j in range(len(DOM_ORDER)):
        v = matrix[i, j]
        if v > 0:
            ax.text(j, i, str(v), ha="center", va="center", fontsize=10,
                    color="white" if v > 60 else "black", fontweight="bold")
plt.colorbar(im, ax=ax, label="Grant count", shrink=0.8)
plt.tight_layout()
fig.savefig(FIG_DIR / "fig2_tier_domain_heatmap.png", dpi=150, bbox_inches="tight")
plt.close()
print("fig2 done")

# ── Fig 3: Score distribution by tier ─────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
tier_scores = [[g._norm_score for g in filtered if g._tier == t] for t in [1,2,3,4]]
bp = ax.boxplot(tier_scores,
                labels=["T1 Must Apply\n(n=136)","T2 Prepare\n(n=211)",
                        "T3 Monitor\n(n=300)","T4 Archive\n(n=251)"],
                patch_artist=True,
                medianprops={"color":"black","linewidth":2})
for patch, t in zip(bp["boxes"], [1,2,3,4]):
    patch.set_facecolor(TIER_COLORS[t])
    patch.set_alpha(0.75)
ax.axhline(0.15, color="#1a7340", linestyle="--", alpha=0.6, linewidth=1.5, label="Tier 1 threshold (0.15)")
ax.axhline(0.12, color="#2471a3", linestyle="--", alpha=0.6, linewidth=1.5, label="Tier 2 threshold (0.12)")
ax.axhline(0.08, color="#d68910", linestyle="--", alpha=0.6, linewidth=1.5, label="Tier 3 threshold (0.08)")
ax.set_ylabel("Normalized Relevance Score (0–1)", fontsize=10)
ax.set_title("Relevance Score by Priority Tier", fontsize=12, fontweight="bold")
ax.set_ylim(0, 0.35)
ax.legend(fontsize=8, loc="upper right")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "fig3_score_by_tier.png", dpi=150, bbox_inches="tight")
plt.close()
print("fig3 done")

# ── Fig 4: Stacked bar: Funding type × Tier ───────────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
x = np.arange(len(FT_ORDER))
bottoms = np.zeros(len(FT_ORDER))
for tier in [1,2,3,4]:
    bar_vals = [sum(1 for g in filtered if g._funding_type == ft and g._tier == tier) for ft in FT_ORDER]
    bars = ax.bar(x, bar_vals, 0.6, bottom=bottoms, color=TIER_COLORS[tier],
                  label=f"T{tier}", alpha=0.85)
    for xi, bv, bot in zip(x, bar_vals, bottoms):
        if bv > 8:
            ax.text(xi, bot + bv/2, str(bv), ha="center", va="center",
                    fontsize=8.5, color="white", fontweight="bold")
    bottoms += np.array(bar_vals, dtype=float)

ax.set_xticks(x)
ax.set_xticklabels([FT_SHORT[k].replace("\n"," ") for k in FT_ORDER], rotation=18, ha="right", fontsize=9)
ax.set_ylabel("Grant Count")
ax.set_title("Priority Tier Distribution by Funding Type", fontsize=12, fontweight="bold")
ax.legend(title="Priority Tier", loc="upper right")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "fig4_funding_type_tier.png", dpi=150, bbox_inches="tight")
plt.close()
print("fig4 done")

# ── Fig 5: Decision tree flowchart (text-based diagram) ───────────────
fig, ax = plt.subplots(figsize=(14, 8))
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis("off")
ax.set_facecolor("#f8f9fa")
fig.patch.set_facecolor("#f8f9fa")

def box(ax, x, y, w, h, text, color="#2471a3", textcolor="white", fontsize=8.5, alpha=0.9):
    rect = mpatches.FancyBboxPatch((x-w/2, y-h/2), w, h,
                                    boxstyle="round,pad=0.1",
                                    facecolor=color, edgecolor="white",
                                    linewidth=1.5, alpha=alpha)
    ax.add_patch(rect)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize,
            color=textcolor, fontweight="bold", wrap=True,
            multialignment="center")

def arrow(ax, x1, y1, x2, y2, label="", color="#555"):
    ax.annotate("", xy=(x2,y2), xytext=(x1,y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=1.5))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx+0.1, my, label, fontsize=7.5, color=color, fontstyle="italic")

ax.set_title("Grant Classification Decision Tree — IPK MECE Taxonomy",
             fontsize=13, fontweight="bold", pad=10)

# Root
box(ax, 7, 7.3, 4, 0.7, "Grant passes AMR+AI keyword filter\n(min 1 AMR + 1 AI hit)", "#1a1a2e")

# Eligibility split
arrow(ax, 7, 6.95, 7, 6.25)
box(ax, 7, 5.9, 4, 0.65, "Step 1: Eligibility Check\n(IPK rules engine)", "#34495e")

arrow(ax, 5, 5.6, 2.5, 5.0, "ineligible")
arrow(ax, 7, 5.6, 7, 5.0, "uncertain")
arrow(ax, 9, 5.6, 11.5, 5.0, "eligible")

# Ineligible branch
box(ax, 2.5, 4.65, 2.8, 0.6, "TIER 4 ARCHIVE\n(72 grants, 8%)", TIER_COLORS[4])

# Funding type
arrow(ax, 7, 4.7, 7, 4.1)
box(ax, 7, 3.75, 4, 0.65, "Step 2: Funding Type\n(Activity code prefix)", "#34495e")

arrow(ax, 5.5, 3.45, 3.5, 2.8, "K/F series")
box(ax, 3.5, 2.5, 2.5, 0.55, "Individual Award\n-> T4 if uncertain", "#8e44ad", fontsize=8)

arrow(ax, 7, 3.45, 7, 2.8)
box(ax, 7, 2.5, 3.2, 0.55, "R/U/P series\n(institutional eligible)", "#34495e")

# Domain
arrow(ax, 7, 2.2, 7, 1.6)
box(ax, 7, 1.3, 3.5, 0.55, "Step 3: Research Domain\n(keyword co-occurrence)", "#34495e")

# Tier outcomes
arrow(ax, 5.5, 1.05, 2.2, 0.55, "AMR+AI >=2 hits\n+ score >= 0.15")
box(ax, 2.2, 0.3, 2.8, 0.5, "TIER 1 MUST APPLY\n136 grants (15.1%)", TIER_COLORS[1])

arrow(ax, 7, 1.05, 7, 0.55, "AMR core\n+ score >= 0.12")
box(ax, 7, 0.3, 2.8, 0.5, "TIER 2 PREPARE\n211 grants (23.5%)", TIER_COLORS[2])

arrow(ax, 8.5, 1.05, 10.2, 0.55, "score >= 0.08\n(any domain)")
box(ax, 10.2, 0.3, 2.8, 0.5, "TIER 3 MONITOR\n300 grants (33.4%)", TIER_COLORS[3])

# Legend
legend_patches = [
    mpatches.Patch(color=TIER_COLORS[1], label="T1: Must Apply (eligible + score>=0.15 + AMR/AI core)"),
    mpatches.Patch(color=TIER_COLORS[2], label="T2: Prepare (eligible/uncertain + score>=0.12 + AMR)"),
    mpatches.Patch(color=TIER_COLORS[3], label="T3: Monitor (score>=0.08, any eligible/uncertain)"),
    mpatches.Patch(color=TIER_COLORS[4], label="T4: Archive (ineligible or K/F uncertain or score<0.08)"),
]
ax.legend(handles=legend_patches, loc="upper right", fontsize=7.5,
          framealpha=0.9, title="Priority Tier Rules", title_fontsize=8)

plt.tight_layout()
fig.savefig(FIG_DIR / "fig5_decision_tree.png", dpi=150, bbox_inches="tight")
plt.close()
print("fig5 done")

# ── Fig 6: Tier 1 deep dive — top 20 grants ───────────────────────────
tier1 = sorted([g for g in filtered if g._tier == 1], key=lambda g: -g._norm_score)[:20]
fig, ax = plt.subplots(figsize=(14, 8))
y_pos = range(len(tier1))
scores = [g._norm_score for g in tier1]
amounts = [(g.amount_max or g.amount_min or 0)/1e6 for g in tier1]
labels_t1 = [f"{g.title[:55]}..." if len(g.title) > 55 else g.title for g in tier1]

bars = ax.barh(list(y_pos), scores, color="#1a7340", alpha=0.8)
ax.set_yticks(list(y_pos))
ax.set_yticklabels(labels_t1, fontsize=7.5)
ax.set_xlabel("Normalized Relevance Score")
ax.set_title("Top 20 Tier 1 'Must Apply' Grants by Relevance Score", fontsize=11, fontweight="bold")
ax.axvline(0.15, color="red", linestyle="--", alpha=0.5, label="Tier 1 threshold")

for i, (bar, amt) in enumerate(zip(bars, amounts)):
    amt_str = f"${amt:.2f}M" if amt > 0 else "N/A"
    ax.text(bar.get_width() + 0.002, bar.get_y() + bar.get_height()/2,
            amt_str, va="center", fontsize=7, color="#555")

ax.legend(fontsize=8)
ax.grid(axis="x", alpha=0.3)
ax.invert_yaxis()
plt.tight_layout()
fig.savefig(FIG_DIR / "fig6_tier1_top20.png", dpi=150, bbox_inches="tight")
plt.close()
print("fig6 done")

print(f"\nAll figures saved to: {FIG_DIR}")
