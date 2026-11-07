---
type: Decision
title: Documentazione in formato OKF
description: La documentazione del progetto è un bundle Open Knowledge Format nella cartella knowledge/.
tags: [okf, documentazione]
status: stable
generated: { by: ai:claude, at: 2026-11-07T00:00:00Z }
sources:
  - resource: https://okf.md/skill/
    title: OKF Skill
---

# Documentazione in formato OKF

## Decisione
La conoscenza del progetto vive in `knowledge/` come bundle [Open Knowledge Format](https://okf.md/skill/) v0.2,
accanto a `CLAUDE.md` (che resta il punto d'ingresso breve per l'assistente) e ai README.

## Regole di conformità
1. Ogni `.md` che non sia `index.md` o `log.md` ha un frontmatter YAML valido.
2. Il frontmatter ha un `type` non vuoto.
3. `index.md` e `log.md` seguono la loro struttura (nessun frontmatter, tranne `okf_version` nell'index radice).

## Come mantenerlo
- Un concetto per file; l'ID è il percorso senza `.md`.
- Link markdown con percorso assoluto dalla radice del bundle, es. `[partizioni](/firmware/partitions.md)`.
- Ogni modifica va annotata in `log.md`, con le date più recenti in alto.
- Non inserire segreti (chiavi API, token, password Wi-Fi) nel bundle.
- Se si modifica un fatto verificato su hardware, aggiornare `verified` o rimuoverlo.
