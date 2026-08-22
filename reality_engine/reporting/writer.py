"""
Report Writer Module
Exports DailyAlphaReport intelligence into multi-format representations:
JSON (machine-readable), Markdown (document/terminal), and HTML (browser-styled dashboard).
"""

from __future__ import annotations

import json
import logging
import html
from pathlib import Path
from typing import Any, Dict, List, Optional

from reality_engine.config import REPORTS_DIR
from reality_engine.agent.schemas import DailyAlphaReport, ScripAlphaThesis, MarketBreadthSummary

logger = logging.getLogger("reality_engine.reporting.writer")


class ReportWriter:
    """
    Exports DailyAlphaReport to JSON, Markdown, and self-contained HTML dashboards.
    """

    def __init__(self, base_reports_dir: Optional[Path] = None):
        self.base_dir = Path(base_reports_dir) if base_reports_dir else REPORTS_DIR

    def export_daily_alpha_report(
        self,
        report: DailyAlphaReport,
        output_dir: Optional[Path] = None
    ) -> Dict[str, Path]:
        """
        Exports the DailyAlphaReport into `daily_alpha.json`, `daily_alpha.md`,
        and `daily_alpha.html` under `reality_engine/data/reports/YYYY-MM-DD/`.
        """
        target_dir = Path(output_dir) if output_dir else (self.base_dir / report.date)
        target_dir.mkdir(parents=True, exist_ok=True)

        json_path = target_dir / "daily_alpha.json"
        md_path = target_dir / "daily_alpha.md"
        html_path = target_dir / "daily_alpha.html"

        self.write_json(report, json_path)
        self.write_markdown(report, md_path)
        self.write_html(report, html_path)

        logger.info("Successfully exported Daily Alpha Report to %s (JSON, MD, HTML)", target_dir)
        return {
            "json": json_path,
            "markdown": md_path,
            "html": html_path,
        }

    def write_json(self, report: DailyAlphaReport, path: Path) -> Path:
        """Writes the report as formatted JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = report.to_dict() if hasattr(report, "to_dict") else report.dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return path

    def write_markdown(self, report: DailyAlphaReport, path: Path) -> Path:
        """Writes the report as a clean, structured Markdown dossier."""
        path.parent.mkdir(parents=True, exist_ok=True)
        mb: MarketBreadthSummary = report.market_breadth

        md_lines = [
            f"# Reality Engine - Daily Alpha & Causal Market Report",
            f"**Valuation Date:** `{report.date}` | **Screened Universe:** `{report.universe}` | **Generated:** `{report.generated_timestamp}`",
            "",
            "---",
            "",
            "## 1. Executive Market Breadth & Macro Regime",
            "",
            f"- **Market Regime:** `{mb.market_regime}`",
            f"- **Advance / Decline Ratio:** `{mb.advance_decline_ratio:.2f}`",
            f"- **Top Performing Sectors:** {', '.join(mb.top_performing_sectors) if mb.top_performing_sectors else 'N/A'}",
            f"- **Vulnerable / Lagging Sectors:** {', '.join(mb.vulnerable_sectors) if mb.vulnerable_sectors else 'N/A'}",
            f"- **Forensic Solvency Disqualifications:** `{report.disqualified_solvency_count} companies rejected`",
            "",
            "---",
            "",
            "## 2. High-Conviction Alpha Candidate Summary",
            "",
            "| Rank | Symbol | Company Name | CMP (INR) | Recommended Entry Range | Target (INR) | Stop Loss (INR) | R:R Ratio | Conviction |",
            "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]

        for t in report.high_conviction_theses:
            md_lines.append(
                f"| #{t.composite_rank} | **{t.symbol}** | {t.company_name} | ₹{t.current_market_price:,.2f} | "
                f"{t.recommended_entry_range} | ₹{t.target_price:,.2f} | ₹{t.stop_loss:,.2f} | "
                f"{t.risk_reward_ratio:.1f}x | `{t.conviction_level}` |"
            )

        md_lines.extend([
            "",
            "---",
            "",
            "## 3. Deep Single-Stock Alpha Theses",
            ""
        ])

        for t in report.high_conviction_theses:
            md_lines.extend([
                f"### #{t.composite_rank} {t.symbol} - {t.company_name}",
                f"**Conviction Level:** `{t.conviction_level}` | **Current Market Price:** `₹{t.current_market_price:,.2f}`",
                "",
                "> **Trade Setup Matrix:**",
                f"> - **Entry Range:** {t.recommended_entry_range}",
                f"> - **Target Price:** ₹{t.target_price:,.2f} (+{((t.target_price - t.current_market_price) / t.current_market_price * 100):.1f}% upside)",
                f"> - **Stop Loss:** ₹{t.stop_loss:,.2f} (-{((t.current_market_price - t.stop_loss) / t.current_market_price * 100):.1f}% risk)",
                f"> - **Risk-to-Reward Ratio:** {t.risk_reward_ratio:.2f}x",
                "",
                "#### Technical Flow & Institutional Delivery Momentum",
                f"{t.techno_delivery_thesis}",
                "",
                "#### Fundamental Acceleration & Margin Expansion",
                f"{t.fundamental_thesis}",
                "",
                "#### Causal Macro Transmission & Value Chain Moat",
                f"{t.causal_macro_rationale}",
                "",
                "#### Key Catalysts & Growth Triggers",
            ])
            for cat in t.key_catalysts:
                md_lines.append(f"- {cat}")

            md_lines.extend([
                "",
                "#### Key Risks & Downside Sensitivities",
            ])
            for risk in t.key_risks:
                md_lines.append(f"- {risk}")

            md_lines.extend(["", "---", ""])

        # Macro Shock Radar section
        if report.macro_shock_radar:
            md_lines.extend([
                "## 4. Macroeconomic Shock & Causal Policy Radar",
                "",
                "| Scenario / Shock Trigger | Key Beneficiary Stocks | Vulnerable Stocks | Resilient / Impaired Ratio |",
                "| :--- | :--- | :--- | :---: |"
            ])
            for s in report.macro_shock_radar:
                name = s.get("scenario_name", s.get("scenario_id", "Scenario"))
                bens = ", ".join(s.get("beneficiaries", [])) or "None Identified"
                vics = ", ".join(s.get("victims", [])) or "None Identified"
                res_cnt = s.get("resilient_count", 0)
                imp_cnt = s.get("impaired_count", 0)
                md_lines.append(f"| **{name}** | {bens} | {vics} | {res_cnt} Resilient / {imp_cnt} Impaired |")
            md_lines.extend(["", "---", ""])

        md_lines.extend([
            "## 5. Forensic Solvency Gate & Governance Audit",
            f"- **Universe Total Analyzed:** `{report.universe}`",
            f"- **Solvency Gate Disqualifications:** `{report.disqualified_solvency_count}` stocks rejected due to high promoter pledge (>15%), insufficient interest coverage (<2.5x), or excessive leverage (>1.5x D/E).",
            "- **Integrity Standard:** Only strictly solvent, non-value-trap equities are qualified for alpha thesis generation.",
            "",
            "---",
            "*Report auto-generated by Reality Engine AI Orchestrator.*"
        ])

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        return path

    def write_html(self, report: DailyAlphaReport, path: Path) -> Path:
        """Writes the report as a modern, self-contained HTML dashboard."""
        path.parent.mkdir(parents=True, exist_ok=True)
        mb: MarketBreadthSummary = report.market_breadth

        # Theme helpers
        regime_class = "regime-bullish" if mb.market_regime in ["BULLISH", "ACCUMULATION"] else ("regime-amber" if mb.market_regime in ["DISTRIBUTION", "VOLATILE"] else "regime-neutral")

        # Table rows
        table_rows_html = []
        for t in report.high_conviction_theses:
            upside_pct = ((t.target_price - t.current_market_price) / max(0.01, t.current_market_price)) * 100.0
            downside_pct = ((t.current_market_price - t.stop_loss) / max(0.01, t.current_market_price)) * 100.0
            conv_pill_class = "pill-high" if t.conviction_level == "HIGH_CONVICTION" else ("pill-mod" if t.conviction_level == "MODERATE" else "pill-spec")

            table_rows_html.append(f"""
            <tr>
                <td class="text-center font-bold">#{t.composite_rank}</td>
                <td><strong class="symbol-link">{html.escape(t.symbol)}</strong></td>
                <td>{html.escape(t.company_name)}</td>
                <td class="text-right font-mono">₹{t.current_market_price:,.2f}</td>
                <td class="text-center font-mono">{html.escape(t.recommended_entry_range)}</td>
                <td class="text-right font-mono text-green">₹{t.target_price:,.2f} <span class="badge-sub">(+{upside_pct:.1f}%)</span></td>
                <td class="text-right font-mono text-red">₹{t.stop_loss:,.2f} <span class="badge-sub">(-{downside_pct:.1f}%)</span></td>
                <td class="text-center font-mono font-bold text-accent">{t.risk_reward_ratio:.1f}x</td>
                <td class="text-center"><span class="pill {conv_pill_class}">{html.escape(t.conviction_level)}</span></td>
            </tr>
            """)

        # Detailed cards
        cards_html = []
        for t in report.high_conviction_theses:
            upside_pct = ((t.target_price - t.current_market_price) / max(0.01, t.current_market_price)) * 100.0
            downside_pct = ((t.current_market_price - t.stop_loss) / max(0.01, t.current_market_price)) * 100.0
            conv_pill_class = "pill-high" if t.conviction_level == "HIGH_CONVICTION" else ("pill-mod" if t.conviction_level == "MODERATE" else "pill-spec")

            catalysts_li = "".join(f"<li><span class=\"bullet-icon bullet-green\">✓</span> {html.escape(c)}</li>" for c in t.key_catalysts)
            risks_li = "".join(f"<li><span class=\"bullet-icon bullet-amber\">⚠</span> {html.escape(r)}</li>" for r in t.key_risks)

            cards_html.append(f"""
            <div class="thesis-card">
                <div class="thesis-header">
                    <div class="thesis-title-area">
                        <span class="rank-badge">#{t.composite_rank}</span>
                        <div>
                            <h3 class="thesis-title">{html.escape(t.symbol)} <span class="company-sub">{html.escape(t.company_name)}</span></h3>
                        </div>
                    </div>
                    <div>
                        <span class="pill {conv_pill_class}">{html.escape(t.conviction_level)}</span>
                    </div>
                </div>

                <div class="setup-grid">
                    <div class="setup-box">
                        <div class="setup-label">CURRENT PRICE</div>
                        <div class="setup-value font-mono">₹{t.current_market_price:,.2f}</div>
                    </div>
                    <div class="setup-box">
                        <div class="setup-label">ENTRY RANGE</div>
                        <div class="setup-value font-mono">{html.escape(t.recommended_entry_range)}</div>
                    </div>
                    <div class="setup-box target-box">
                        <div class="setup-label">TARGET PRICE (+{upside_pct:.1f}%)</div>
                        <div class="setup-value font-mono text-green">₹{t.target_price:,.2f}</div>
                    </div>
                    <div class="setup-box sl-box">
                        <div class="setup-label">STOP LOSS (-{downside_pct:.1f}%)</div>
                        <div class="setup-value font-mono text-red">₹{t.stop_loss:,.2f}</div>
                    </div>
                    <div class="setup-box">
                        <div class="setup-label">RISK : REWARD</div>
                        <div class="setup-value font-mono text-accent">{t.risk_reward_ratio:.2f}x</div>
                    </div>
                </div>

                <div class="thesis-body-grid">
                    <div class="thesis-section-block">
                        <h4 class="section-subtitle"><span class="icon">📊</span> Technical Flow & Delivery Momentum</h4>
                        <p class="section-text">{html.escape(t.techno_delivery_thesis)}</p>
                    </div>
                    <div class="thesis-section-block">
                        <h4 class="section-subtitle"><span class="icon">📈</span> Fundamental Acceleration & Margins</h4>
                        <p class="section-text">{html.escape(t.fundamental_thesis)}</p>
                    </div>
                    <div class="thesis-section-block">
                        <h4 class="section-subtitle"><span class="icon">🌐</span> Causal Macro & Value Chain Rationale</h4>
                        <p class="section-text">{html.escape(t.causal_macro_rationale)}</p>
                    </div>
                </div>

                <div class="catalysts-risks-grid">
                    <div class="cat-risk-box cat-box">
                        <h4 class="cat-risk-title text-green">Growth Catalysts & Triggers</h4>
                        <ul class="cat-risk-list">
                            {catalysts_li}
                        </ul>
                    </div>
                    <div class="cat-risk-box risk-box">
                        <h4 class="cat-risk-title text-amber">Sensitivities & Downside Risks</h4>
                        <ul class="cat-risk-list">
                            {risks_li}
                        </ul>
                    </div>
                </div>
            </div>
            """)

        # Radar rows
        radar_rows_html = []
        for s in (report.macro_shock_radar or []):
            name = s.get("scenario_name", s.get("scenario_id", "Scenario"))
            bens = s.get("beneficiaries", [])
            vics = s.get("victims", [])
            bens_badges = " ".join(f"<span class=\"pill pill-high\">{html.escape(b)}</span>" for b in bens) if bens else "<span class=\"text-muted\">None</span>"
            vics_badges = " ".join(f"<span class=\"pill pill-sl\">{html.escape(v)}</span>" for v in vics) if vics else "<span class=\"text-muted\">None</span>"
            res_cnt = s.get("resilient_count", 0)
            imp_cnt = s.get("impaired_count", 0)

            radar_rows_html.append(f"""
            <tr>
                <td><strong>{html.escape(name)}</strong></td>
                <td>{bens_badges}</td>
                <td>{vics_badges}</td>
                <td class="text-center font-mono"><span class="text-green font-bold">{res_cnt}</span> / <span class="text-red font-bold">{imp_cnt}</span></td>
            </tr>
            """)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reality Engine | Daily Alpha Report - {html.escape(report.date)}</title>
    <style>
        :root {{
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --border-color: #30363d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-amber: #d29922;
            --accent-purple: #bc8cff;
            --card-radius: 10px;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.5;
            padding: 24px;
        }}
        .container {{ max-width: 1280px; margin: 0 auto; }}
        
        /* Header */
        .header {{
            background: linear-gradient(135deg, #161b22 0%, #1c2430 100%);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            padding: 24px 32px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .header-title {{ font-size: 26px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }}
        .header-tag {{ background: rgba(88, 166, 255, 0.15); color: var(--accent-blue); padding: 4px 10px; border-radius: 6px; font-size: 13px; font-weight: 600; }}
        .header-meta {{ color: var(--text-secondary); font-size: 14px; margin-top: 6px; }}
        
        /* KPI Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            padding: 18px 20px;
        }}
        .kpi-label {{ font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.5px; }}
        .kpi-value {{ font-size: 24px; font-weight: 700; margin-top: 6px; }}
        .kpi-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}
        
        /* Pills & Badges */
        .pill {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }}
        .pill-high {{ background: rgba(63, 185, 80, 0.15); color: var(--accent-green); border: 1px solid rgba(63, 185, 80, 0.3); }}
        .pill-mod {{ background: rgba(88, 166, 255, 0.15); color: var(--accent-blue); border: 1px solid rgba(88, 166, 255, 0.3); }}
        .pill-spec {{ background: rgba(188, 140, 255, 0.15); color: var(--accent-purple); border: 1px solid rgba(188, 140, 255, 0.3); }}
        .pill-sl {{ background: rgba(248, 81, 73, 0.15); color: var(--accent-red); border: 1px solid rgba(248, 81, 73, 0.3); }}
        .regime-bullish {{ color: var(--accent-green); }}
        .regime-amber {{ color: var(--accent-amber); }}
        .regime-neutral {{ color: var(--accent-blue); }}
        
        /* Tables */
        .table-container {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            overflow-x: auto;
            margin-bottom: 32px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            text-align: left;
        }}
        th {{
            background: var(--bg-tertiary);
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-color);
        }}
        td {{
            padding: 14px 16px;
            border-bottom: 1px solid var(--border-color);
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: rgba(255, 255, 255, 0.02); }}
        
        /* Typography helpers */
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .font-bold {{ font-weight: 700; }}
        .font-mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }}
        .text-green {{ color: var(--accent-green); }}
        .text-red {{ color: var(--accent-red); }}
        .text-amber {{ color: var(--accent-amber); }}
        .text-accent {{ color: var(--accent-blue); }}
        .text-muted {{ color: var(--text-muted); }}
        .badge-sub {{ font-size: 11px; font-weight: normal; opacity: 0.85; }}
        
        /* Section Heading */
        .section-header {{
            font-size: 19px;
            font-weight: 700;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
            color: #fff;
        }}
        
        /* Thesis Cards */
        .thesis-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            padding: 24px;
            margin-bottom: 24px;
        }}
        .thesis-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 14px;
            border-bottom: 1px solid var(--border-color);
        }}
        .thesis-title-area {{ display: flex; align-items: center; gap: 14px; }}
        .rank-badge {{
            background: var(--bg-tertiary);
            color: var(--accent-blue);
            font-size: 14px;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        .thesis-title {{ font-size: 20px; font-weight: 700; color: #fff; }}
        .company-sub {{ font-size: 14px; font-weight: 400; color: var(--text-secondary); margin-left: 6px; }}
        
        /* Setup Grid */
        .setup-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }}
        .setup-box {{
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px 14px;
        }}
        .target-box {{ border-color: rgba(63, 185, 80, 0.35); }}
        .sl-box {{ border-color: rgba(248, 81, 73, 0.35); }}
        .setup-label {{ font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; }}
        .setup-value {{ font-size: 16px; font-weight: 700; margin-top: 4px; }}
        
        /* Thesis Sections */
        .thesis-body-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }}
        .thesis-section-block {{
            background: rgba(255, 255, 255, 0.015);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
        }}
        .section-subtitle {{ font-size: 13px; font-weight: 600; color: var(--accent-blue); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }}
        .section-text {{ font-size: 13px; color: var(--text-primary); line-height: 1.6; }}
        
        /* Catalysts & Risks */
        .catalysts-risks-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        @media (max-width: 768px) {{
            .catalysts-risks-grid {{ grid-template-columns: 1fr; }}
        }}
        .cat-risk-box {{
            border-radius: 8px;
            padding: 14px 16px;
            border: 1px solid var(--border-color);
        }}
        .cat-box {{ background: rgba(63, 185, 80, 0.05); border-color: rgba(63, 185, 80, 0.2); }}
        .risk-box {{ background: rgba(210, 153, 34, 0.05); border-color: rgba(210, 153, 34, 0.2); }}
        .cat-risk-title {{ font-size: 13px; font-weight: 700; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .cat-risk-list {{ list-style: none; }}
        .cat-risk-list li {{ font-size: 13px; margin-bottom: 6px; display: flex; gap: 8px; }}
        .bullet-icon {{ font-weight: bold; flex-shrink: 0; }}
        .bullet-green {{ color: var(--accent-green); }}
        .bullet-amber {{ color: var(--accent-amber); }}
        
        /* Footer */
        .footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 12px;
            padding: 24px 0;
            border-top: 1px solid var(--border-color);
            margin-top: 32px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div>
                <div class="header-title">
                    <span>⚡ Reality Engine</span>
                    <span class="header-tag">DAILY ALPHA INTELLIGENCE</span>
                </div>
                <div class="header-meta">
                    Valuation Date: <strong>{html.escape(report.date)}</strong> &nbsp;|&nbsp; 
                    Universe: <strong>{html.escape(report.universe)}</strong> &nbsp;|&nbsp; 
                    Generated: <strong>{html.escape(report.generated_timestamp)}</strong>
                </div>
            </div>
            <div>
                <span class="pill pill-high font-mono">SOLVENCY CERTIFIED</span>
            </div>
        </div>

        <!-- KPI Grid -->
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Market Regime</div>
                <div class="kpi-value {regime_class}">{html.escape(mb.market_regime)}</div>
                <div class="kpi-sub">Advance/Decline: <strong>{mb.advance_decline_ratio:.2f}</strong></div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Top High-Conviction Picks</div>
                <div class="kpi-value text-accent">{len(report.high_conviction_theses)} Candidates</div>
                <div class="kpi-sub">Multi-factor quant filtered</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Solvency Disqualifications</div>
                <div class="kpi-value text-red">{report.disqualified_solvency_count} Companies</div>
                <div class="kpi-sub">Pledge &gt;15% or Coverage &lt;2.5x</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Macro Radar Scenarios</div>
                <div class="kpi-value text-green">{len(report.macro_shock_radar or [])} Active Shocks</div>
                <div class="kpi-sub">Causal graph stress-tested</div>
            </div>
        </div>

        <!-- Section 1: Candidate Table -->
        <div class="section-header">🎯 High-Conviction Alpha Portfolio</div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th class="text-center">Rank</th>
                        <th>Symbol</th>
                        <th>Company Name</th>
                        <th class="text-right">CMP</th>
                        <th class="text-center">Entry Range</th>
                        <th class="text-right">Target Price</th>
                        <th class="text-right">Stop Loss</th>
                        <th class="text-center">R:R</th>
                        <th class="text-center">Conviction</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(table_rows_html)}
                </tbody>
            </table>
        </div>

        <!-- Section 2: Detailed Theses -->
        <div class="section-header">📑 Deep Scrip Alpha Theses</div>
        {"".join(cards_html)}

        <!-- Section 3: Macro Radar -->
        <div class="section-header">🌐 Macroeconomic Shock & Policy Transmission Radar</div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Macro Trigger / Shock Scenario</th>
                        <th>Beneficiaries (Positive Elasticity)</th>
                        <th>Victims (Negative Elasticity)</th>
                        <th class="text-center">Resilient / Impaired</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(radar_rows_html)}
                </tbody>
            </table>
        </div>

        <!-- Footer -->
        <div class="footer">
            <p>Reality Engine AI Intelligence & Causal Graph Modeling Platform &bull; strictly for quantitative research & reality verification &bull; {html.escape(report.generated_timestamp)}</p>
        </div>
    </div>
</body>
</html>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return path


# Singleton report writer instance
report_writer = ReportWriter()
