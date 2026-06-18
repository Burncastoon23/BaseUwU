"""
Human-readable renderers for AgentCard objects.

Outputs:
- render_card_text  — terminal-friendly text with emoji trust badges
- render_card_html  — self-contained HTML with inline styles
- render_registry_index — text table of all agents
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime, timezone
from typing import Optional

from .schema import AgentCard, AgentCapability, TrustLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRUST_BADGE: dict[TrustLevel, str] = {
    TrustLevel.AUDITED: "✅ audited",
    TrustLevel.VERIFIED: "✅ verified",
    TrustLevel.SELF_DECLARED: "⚠️  self-declared",
    TrustLevel.UNVERIFIED: "❌ unverified",
}

_TRUST_COLOR: dict[TrustLevel, str] = {
    TrustLevel.AUDITED: "#1a7f37",
    TrustLevel.VERIFIED: "#2da44e",
    TrustLevel.SELF_DECLARED: "#bf8700",
    TrustLevel.UNVERIFIED: "#cf222e",
}

_TRUST_BG: dict[TrustLevel, str] = {
    TrustLevel.AUDITED: "#dafbe1",
    TrustLevel.VERIFIED: "#dafbe1",
    TrustLevel.SELF_DECLARED: "#fff8c5",
    TrustLevel.UNVERIFIED: "#ffebe9",
}

_TRUST_ICON: dict[TrustLevel, str] = {
    TrustLevel.AUDITED: "✅",
    TrustLevel.VERIFIED: "✅",
    TrustLevel.SELF_DECLARED: "⚠️",
    TrustLevel.UNVERIFIED: "❌",
}


def _age_label(dt: Optional[datetime]) -> str:
    """Return a human-readable age string for a datetime, or 'never'."""
    if dt is None:
        return "never"
    now = datetime.now(timezone.utc)
    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "in the future"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m ago"
    if total_seconds < 86_400:
        return f"{total_seconds // 3600}h ago"
    days = total_seconds // 86_400
    return f"{days}d ago"


def _freshness_label(dt: Optional[datetime], ttl_seconds: int) -> str:
    """Return 'verified Xh ago' or 'stale: Xd ago'."""
    if dt is None:
        return "never verified"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_s = (now - dt).total_seconds()
    age_str = _age_label(dt)
    if age_s <= ttl_seconds:
        return f"verified {age_str}"
    return f"stale: {age_str}"


def _success_bar(rate: float, width: int = 10) -> str:
    """ASCII progress bar for success rate."""
    filled = round(rate * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {rate * 100:.0f}%"


def _esc(text: str) -> str:
    return html_lib.escape(str(text))


# ---------------------------------------------------------------------------
# Text renderer
# ---------------------------------------------------------------------------

def render_card_text(card: AgentCard) -> str:
    """Return a terminal-friendly capability card string."""
    lines: list[str] = []

    badge = _TRUST_BADGE[card.trust_level]
    freshness = _freshness_label(card.verification_date, card.ttl_seconds)

    lines.append("╔" + "═" * 62 + "╗")
    lines.append(f"║  {card.name}  (v{card.version})".ljust(63) + "║")
    lines.append(f"║  {badge}  •  {freshness}".ljust(63) + "║")
    lines.append("╠" + "═" * 62 + "╣")
    lines.append(f"║  ID       : {card.agent_id}".ljust(63) + "║")
    lines.append(f"║  Provider : {card.provider or '—'}".ljust(63) + "║")
    lines.append(f"║  Endpoint : {card.endpoint or '—'}".ljust(63) + "║")
    if card.description:
        # Wrap description at ~58 chars
        desc = card.description
        while len(desc) > 58:
            lines.append(f"║  {desc[:58]}".ljust(63) + "║")
            desc = desc[58:]
        lines.append(f"║  {desc}".ljust(63) + "║")
    lines.append("╠" + "═" * 62 + "╣")
    lines.append("║  CAPABILITIES".ljust(63) + "║")

    if not card.skills:
        lines.append("║  (none declared)".ljust(63) + "║")
    else:
        for skill in card.skills:
            verified_icon = "✅" if skill.verified else "⬜"
            lines.append(f"║  {verified_icon} {skill.name}".ljust(63) + "║")
            if skill.description:
                desc = skill.description[:55]
                lines.append(f"║      {desc}".ljust(63) + "║")
            bar = _success_bar(skill.success_rate)
            lv_label = (
                f"  last verified: {_age_label(skill.last_verified)}"
                if skill.last_verified
                else ""
            )
            lines.append(f"║      {bar}{lv_label}".ljust(63) + "║")
            if skill.input_types:
                in_str = ", ".join(skill.input_types[:4])
                lines.append(f"║      in : {in_str}".ljust(63) + "║")
            if skill.output_types:
                out_str = ", ".join(skill.output_types[:4])
                lines.append(f"║      out: {out_str}".ljust(63) + "║")

    lines.append("╚" + "═" * 62 + "╝")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def render_card_html(card: AgentCard) -> str:
    """Return a self-contained HTML capability card (inline styles only)."""
    trust_color = _TRUST_COLOR[card.trust_level]
    trust_bg = _TRUST_BG[card.trust_level]
    badge = _TRUST_BADGE[card.trust_level]
    freshness = _freshness_label(card.verification_date, card.ttl_seconds)

    skills_html = ""
    for skill in card.skills:
        v_icon = "✅" if skill.verified else "⬜"
        bar_pct = int(skill.success_rate * 100)
        bar_color = "#2da44e" if skill.success_rate >= 0.8 else (
            "#bf8700" if skill.success_rate >= 0.5 else "#cf222e"
        )
        lv_label = (
            f"<span style='color:#666;font-size:0.8em;'>last verified: "
            f"{_esc(_age_label(skill.last_verified))}</span>"
            if skill.last_verified else ""
        )
        in_str = _esc(", ".join(skill.input_types[:4])) if skill.input_types else ""
        out_str = _esc(", ".join(skill.output_types[:4])) if skill.output_types else ""

        skills_html += f"""
        <div style="border:1px solid #e1e4e8;border-radius:6px;padding:10px 14px;
                    margin-bottom:8px;background:#fff;">
          <div style="font-weight:600;font-size:0.95em;">{v_icon} {_esc(skill.name)}</div>
          <div style="color:#555;font-size:0.85em;margin:4px 0;">{_esc(skill.description)}</div>
          <div style="display:flex;align-items:center;gap:8px;margin:6px 0;">
            <div style="flex:1;background:#e1e4e8;border-radius:4px;height:8px;">
              <div style="width:{bar_pct}%;background:{bar_color};height:8px;
                          border-radius:4px;"></div>
            </div>
            <span style="font-size:0.8em;color:{bar_color};font-weight:600;">{bar_pct}%</span>
            {lv_label}
          </div>
          {"<div style='font-size:0.78em;color:#666;'>in: " + in_str + "</div>" if in_str else ""}
          {"<div style='font-size:0.78em;color:#666;'>out: " + out_str + "</div>" if out_str else ""}
        </div>"""

    if not skills_html:
        skills_html = "<p style='color:#888;font-style:italic;'>No capabilities declared.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_esc(card.name)} — Agent Card</title>
</head>
<body style="font-family:system-ui,sans-serif;max-width:680px;margin:40px auto;
             color:#24292f;background:#f6f8fa;padding:0 16px;">

  <div style="background:#fff;border:1px solid #d0d7de;border-radius:8px;
              padding:24px 28px;box-shadow:0 1px 3px rgba(0,0,0,.1);">

    <!-- header -->
    <div style="display:flex;justify-content:space-between;align-items:flex-start;
                flex-wrap:wrap;gap:8px;">
      <div>
        <h1 style="margin:0 0 4px;font-size:1.4em;">{_esc(card.name)}</h1>
        <span style="font-size:0.85em;color:#666;">v{_esc(card.version)}</span>
      </div>
      <span style="background:{trust_bg};color:{trust_color};border:1px solid {trust_color};
                   border-radius:20px;padding:4px 12px;font-size:0.85em;font-weight:600;
                   white-space:nowrap;">{badge}</span>
    </div>

    <!-- freshness -->
    <p style="margin:8px 0 16px;font-size:0.85em;color:#666;">{_esc(freshness)}</p>

    <!-- meta -->
    <table style="width:100%;border-collapse:collapse;font-size:0.88em;margin-bottom:20px;">
      <tr>
        <td style="padding:4px 8px 4px 0;color:#666;white-space:nowrap;">Agent ID</td>
        <td style="padding:4px 0;font-family:monospace;">{_esc(card.agent_id)}</td>
      </tr>
      <tr>
        <td style="padding:4px 8px 4px 0;color:#666;">Provider</td>
        <td style="padding:4px 0;">{_esc(card.provider) or "—"}</td>
      </tr>
      <tr>
        <td style="padding:4px 8px 4px 0;color:#666;">Endpoint</td>
        <td style="padding:4px 0;font-family:monospace;">{_esc(card.endpoint) or "—"}</td>
      </tr>
    </table>

    {f'<p style="margin:0 0 20px;color:#444;font-size:0.92em;">{_esc(card.description)}</p>' if card.description else ""}

    <!-- capabilities -->
    <h2 style="font-size:1em;text-transform:uppercase;letter-spacing:.05em;
               color:#666;margin:0 0 10px;border-top:1px solid #e1e4e8;padding-top:16px;">
      Capabilities ({len(card.skills)})
    </h2>
    {skills_html}

  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Registry index renderer
# ---------------------------------------------------------------------------

def render_registry_index(cards: list[AgentCard]) -> str:
    """Return a text table listing all agents with trust level and top 3 skills."""
    if not cards:
        return "(registry is empty)"

    col_name = max(len(c.name) for c in cards)
    col_name = max(col_name, 20)
    col_trust = 14
    col_skills = 48

    header = (
        f"{'Agent':<{col_name}}  {'Trust':<{col_trust}}  {'Top Capabilities':<{col_skills}}"
    )
    sep = "-" * len(header)

    rows = [header, sep]
    for card in cards:
        icon = _TRUST_ICON[card.trust_level]
        trust_str = f"{icon} {card.trust_level.value}"
        top_skills = ", ".join(s.name for s in card.skills[:3])
        if len(card.skills) > 3:
            top_skills += f" (+{len(card.skills) - 3} more)"
        rows.append(
            f"{card.name:<{col_name}}  {trust_str:<{col_trust}}  {top_skills:<{col_skills}}"
        )

    rows.append(sep)
    rows.append(f"Total: {len(cards)} agent(s)")
    return "\n".join(rows)
