# Lab Investments polish (round 2)

User feedback on live lab next desks. Classic pages stay byte-stable.

## Locked

1. **Analysis inner scroll** — drop `lg:max-h` + `lg:overflow-y-auto` on `AnalysisCapitalHeroNext`. Page scrolls. Do not restyle `DrawMetricsCard` / fees / staking.
2. **DCA color follows rank** — server score order unchanged. Tone is rank-monotonic (top = green). Do not use `eligible` or `historyIncomplete` for chip color. Delete alert-eligible / display-only tags.
3. **Chrome** — lab next only: no H1/subtitle; one row SubNav + desk switch. Gates mount the switch only on classic. Do not edit `InvestmentsPageShell` / `InvestmentsSubNav` classes.
