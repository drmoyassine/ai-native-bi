---
id: governed-kpis
title: One trusted definition of every KPI
status: active
description: >-
  Every institutional number is defined once, with its steward, version and lineage, and every consumer gets the same
  answer
tags:
  - metrics
  - governance
generated:
  by: agent/claude-code
  at: '2026-10-26T13:23:31.090Z'
related_decisions:
  - id: DEC-002
    name: One institution per deployment
    url: /DECISIONS.md#DEC-002
  - id: DEC-004
    name: Cube is the governed layer and the only read path for KPIs
    url: /DECISIONS.md#DEC-004
  - id: DEC-010
    name: dbt for transforms
    url: /DECISIONS.md#DEC-010
related_roadmap_items:
  - id: ROADMAP-002
    name: 'Phase 1: the pipeline end to end, from files to the AMS'
    url: /ROADMAP.md#ROADMAP-002
modified:
  by: agent/claude-code
  at: '2026-10-26T17:33:38.583Z'
---
# governed-kpis — One trusted definition of every KPI

The institution's numbers (enrollment, retention, graduation, outcomes, faculty, finance, strategic plan) come from many
source systems and are recomputed by hand for each report. The BI defines each KPI once in a governed layer, with its
steward, version and lineage, and serves that one definition to everyone. Success: a dean's dashboard, a self-study and an
AI agent asking the same question get the same number, and anyone can see where it came from.
