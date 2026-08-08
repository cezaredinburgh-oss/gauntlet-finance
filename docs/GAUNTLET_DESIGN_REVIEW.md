## Design Document Review: Gauntlet Finance App — Complete Rebuild Design

### Summary
Approved — 0 open issues.

Rev 3 of `docs/GAUNTLET_DESIGN.md` closes the residual Issues 31–35 from the prior re-review. Issues 1–30 remain addressed from Rev 2. Spot-checks against Collective (alerts envelope, alert thresholds, transfer-match and import ownership already locked in earlier passes) confirm the design is implementation-ready for Phase 0 exit and PR1 scaffold.

---

### Re-review verification (Issues 31–35)

| ID | Topic | Result |
|----|--------|--------|
| 31 | `GET /alerts` envelope | **Addressed.** Documented `{ items, warn_count, danger_count, total }`; forbids key `alerts`; `uncategorized_high` = danger at ≥40%, `uncategorized_pct` = warn ≥20% and &lt;40%. Matches Collective `build_alerts` + AlertsPage `r.items`. |
| 32 | PR14 dependencies | **Addressed.** PR14 depends on **PR12, PR8, PR10**. Verification gate for Bank statements samples is **PR6+PR7**; PR11 is wizard polish + re-verify. |
| 33 | PR count | **Addressed.** Single **PR5** with commits 5a/5b; footer “PR count: 16 (numbered PR1–PR16)”. |
| 34 | Lift policy services | **Addressed.** Verbatim list includes `portfolio_snapshot`, `dashboard`, `prices`, `tax_report`, `lot_costs`, `engines/statements`, `fx_amounts`, `periods`, alerts envelope; KD-16 points at full list. |
| 35 | Start-App vs hard-fail | **Addressed.** Canonical path: API always starts; `spreadsheet_configured: false`; Start-App opens `/setup`; InMemory only tests/`REPO_BACKEND=memory`; optional `REQUIRE_SHEETS` strict exit only. |

No new issues introduced by Rev 3. No prior issues re-opened.

---

### Strengths
- **Non-negotiables are enforceable:** statements-only ParserKey allowlist, Digital Assets seed rule (priority 6) in PR2, fee-net guards, internal-transfer matcher port, 1095-day exemption via config, Fitness + My business tests, ports 8020/5190 as code defaults, USD/CZK Money UX.
- **Parity strategy is clear:** lift/port policy + golden tests; formulas are a critical-path index, not a substitute for Collective modules.
- **Import and ops contracts match Collective reality:** pipeline stages with route-owned cache invalidation; lots only from LotEngine; existing_updates; full Categorize API set; `/admin/*`; alerts catalog and `items` envelope.
- **Start-App path is Agents.md-aligned** without Collective’s silent InMemory demo; setup-first when Sheets is unconfigured.
- **PR plan is ordered and realistic:** Sheets early (PR6), engines independent of parsers, continuous verification milestones, 16 numbered PRs with explicit frontend API deps (including PR14 → PR10).
- **Security and operability:** secrets hygiene, upload allowlist, bind 127.0.0.1, no PII bootstrap keywords, operator runbook for hash re-import and lot rebuild.

---

### Phase 0 exit

| Severity | Open count |
|----------|------------|
| critical | 0 |
| major    | 0 |
| minor    | 0 |
| nit      | 0 |
| **Total open** | **0** |

**Phase 0 may exit.** Proceed to implementation starting with **PR1 — Repository scaffold & toolchains**.

---

### Cumulative issue disposition

| Range | Outcome |
|-------|---------|
| Issues 1–30 (Rev 1→2) | addressed |
| Issues 31–35 (Rev 2→3) | addressed |
| New this pass | none |

---

*Reviewer confirmation: 2026-08-07 — design accepted for implementation.*
)
